"""Scenario test for install.sh: which units `install.sh render` (and so `install.sh units`) covers for an instance
config, and how they render and install as user units — no real sudo, no real systemd, nothing outside a temp dir.

Covers: the portal-sync unit only with [portal] account_id set, anchor-hub's unit only with [anchor_hub] enabled = true, the
three server units and the puller always; a unit named explicitly still renders; render never calls sudo; the usage text.
The units are user units, the only kind since every unit is the plain substitution of its template (the server units'
are written for the user manager: no User=, WantedBy=default.target, no Wants=network-online.target, the reload service
reloads the server and anchor-hub with systemctl --user and watches only the config file; the drop-in carries no
systemctl call) under the header each always had, so an upgrade
reports them unchanged. A config that still says [units] scope = "user", or carries the four [client] mode keys at their one
value, is accepted without a word; scope = "system", an unknown scope, or a removed [client] value is refused with config.py's
line naming the removal. `install.sh units`, against a temp HOME with systemctl stubbed: every unit lands under
~/.config/systemd/user, every systemctl call carries --user, sudo is never called, a second run changes nothing, --start
restarts through the user manager. A system-scope stackshot.service still enabled or running on the box: units refuses before
installing anything; one left disabled and stopped: not a word.
Lingering (loginctl stubbed): `units` and `puller` say it is on when it is; switch it on with `loginctl enable-linger`
when the user may; otherwise try `sudo -n` only, print a WARNING with the root command and still exit 0. --quiet-hint drops the
"changed, not restarted" line. USER unset: install.sh falls back to `id -un`.
The audit's timer pair: rendered and installed only with [audit] enabled = true, its OnCalendar from [audit] at (a
garbage value reads as 05:00) in the instance timezone; `units` enables and starts the timer, never the service, and re-arms
the timer when its file changed; --restart never restarts the service (that would cue an audit); with enabled = false a pair
installed earlier is disabled and removed, and with none installed it is only skipped. [audit] at as a list of times gives
the timer one OnCalendar line each (sorted, once each); the rulebook scan is the service's ExecStartPost, after the run.
The minute runner's unit (stackshot-minute.service): only with [runner] process = "unit" on a box that is not a read-only standby (a bad
value counts as inline). At inline nothing is rendered, installed, enabled, started or restarted for it, no systemctl call asks about a
standby, and every other unit renders to the same bytes as at "unit"; at "unit" it is rendered with each setting the issue names
(checked by key and by section), installed, enabled, and started or restarted after the server; on a standby (the environment of the script
or the user manager's for stackshot.service) it is skipped; back at inline an installed one is stopped, disabled and removed. The reload path
reaches it through ReloadPropagatedFrom, so the reload service stays exactly as it was.
The server host: `units` refuses, in one line before anything is touched (no unit, no loginctl call, no systemctl call but the read that asks whether the box is a standby), on a box that is not
the server host the config names ([release] deploy_ssh, a host word included, or [server] box = false); a deploy_ssh that names this box (its
name, short name or a loopback address) installs; a config naming no server host installs as before; a read-only standby is never refused;
--force-host installs anyway; render and puller are not checked; a host word whose lookup does not resolve is refused and the line says so; a check whose config read fails refuses nothing.

    tests/run-suite install        → exit 0 / 1"""
import os, re, shutil, subprocess, sys, pathlib, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="installtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
# a sudo that records its call and fails: render must never reach it
(T / "bin").mkdir(); (T / "bin/sudo").write_text(f'#!/bin/sh\ntouch {tmp}/sudo-called\necho "$*" >> {tmp}/sudo.log\nexit 1\n'); (T / "bin/sudo").chmod(0o755)
ENV = {**os.environ, "PATH": f"{tmp}/bin:" + os.environ.get("PATH", "")}
for k in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG"): ENV.pop(k, None)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

def conf(name, account_id="", enabled="false", scope=None, client=None, audit=None, at=None, tz=None, project=None, runner=None):
    t, n1 = re.subn(r'(?m)^account_id = "[^"]*"', f'account_id = "{account_id}"', toml)
    t, n2 = re.subn(r'(?m)^(\[anchor_hub\][^\n]*\n)enabled = (true|false)', rf'\g<1>enabled = {enabled}', t)
    assert n1 == 1 and n2 == 1, (n1, n2)
    if audit is not None:                    # [audit] enabled
        t, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = (true|false)', rf'\g<1>enabled = {audit}', t); assert n == 1
    if at is not None:
        lit = "[" + ", ".join(f'"{x}"' for x in at) + "]" if isinstance(at, list) else f'"{at}"'    # a string or a list of them, as the config has it
        t, n = re.subn(r'(?m)^at = (?:"[^"]*"|\[[^\]\n]*\])', lambda m: f'at = {lit}', t); assert n == 1
    if runner is not None:                   # [runner] process
        t, n = re.subn(r'(?m)^process = "[^"]*"', lambda m: f'process = "{runner}"', t); assert n == 1   # the example has one key of that name
    if project is not None:
        t, n = re.subn(r'(?m)^project = "[^"]*"', f'project = "{project}"', t); assert n == 1
    if tz is not None:
        t, n = re.subn(r'(?m)^timezone = "[^"]*"', f'timezone = "{tz}"', t); assert n == 1
    if scope is not None:                    # the key removed, as an older config still carries it
        t += f'\n[units]\nscope = "{scope}"\n'
    if client:                               # the [client] mode keys removed, under the section's url line
        t, n3 = re.subn(r'(?m)^(url = .*)$', lambda m: m.group(1) + "".join(f'\n{k} = "{v}"' for k, v in client.items()), t); assert n3 == 1
    p = T / name; p.write_text(t, encoding="utf-8"); return str(p)

def render(cfg, *names, env=None):
    r = subprocess.run([os.path.join(STACK, "install.sh"), "render", *names, "--config", cfg], capture_output=True, text=True, env=env or ENV)
    return r.returncode, re.findall(r"^# Rendered by install\.sh from units/(\S+)\.in", r.stdout, re.M), r.stdout + r.stderr

def render_out(cfg, *names, env=None):
    r = subprocess.run([os.path.join(STACK, "install.sh"), "render", *names, "--config", cfg], capture_output=True, text=True, env=env or ENV)
    return r.returncode, r.stdout, r.stderr

BASE = ["stackshot.service", "stackshot-reload.service", "stackshot-reload.path"]
rc, units, out = render(conf("off.toml"))
check("off: render succeeds", rc == 0, out[-400:])
check("off: the server units and the puller, no portal-sync, no anchor-hub", units == BASE + ["stackshot-puller.service"], units)

rc, units, out = render(conf("portal.toml", account_id="0123abcd"))
check("account_id set: the portal-sync unit joins", rc == 0 and units == BASE + ["stackshot-portal-sync.service", "stackshot-puller.service"], units)

rc, units, out = render(conf("hub.toml", enabled="true"))
check("anchor_hub enabled: anchor-hub's unit joins", rc == 0 and units == BASE + ["anchor-hub.service", "stackshot-puller.service"], units)

rc, units, out = render(conf("all.toml", account_id="0123abcd", enabled="true"))
check("both on: all six, in the order units installs them", rc == 0 and units == BASE + ["stackshot-portal-sync.service", "anchor-hub.service", "stackshot-puller.service"], units)

t = re.sub(r'(?m)^enabled = false[^\n]*\n', "", toml); (T / "nokey.toml").write_text(t, encoding="utf-8")
rc, units, out = render(str(T / "nokey.toml"))
check("no [anchor_hub] enabled key: off (the code default)", rc == 0 and "anchor-hub.service" not in units, units)

rc, units, out = render(conf("off2.toml"), "stackshot-portal-sync.service", "anchor-hub.service")
check("a unit named explicitly still renders whatever the config says", rc == 0 and units == ["stackshot-portal-sync.service", "anchor-hub.service"], units)
rc, units, out = render(conf("off3.toml"), "stackshot.service.d-portal-sync.conf")
check("the portal drop-in renders on request", rc == 0 and units == ["stackshot.service.d-portal-sync.conf"], out[-300:])
rc, out, err = render_out(conf("wd.toml", account_id="0123abcd"), "stackshot-portal-sync.service")
check("portal-sync runs in the checkout, never the home folder (claude mcp list there sees its local servers)",
      rc == 0 and f"WorkingDirectory={STACK}\n" in out, out[-500:] + err[-200:])

check("render never called sudo", not (T / "sudo-called").exists())

# ---- user units, the only kind
check("the example has no [units] section", re.search(r"(?m)^\[units\]", toml) is None)
SERVER = ["stackshot.service", "stackshot-reload.service", "stackshot-reload.path", "stackshot-portal-sync.service"]
ALL = SERVER + ["anchor-hub.service", "stackshot-puller.service"]
def split_units(text):
    """render's stdout → {unit: its text}, split on the header lines."""
    out = {}
    for m in re.finditer(r"(?ms)^# Rendered by install\.sh from units/(\S+)\.in.*?(?=^# ---------------- |\Z)", text):
        out[m.group(1)] = m.group(0)
    return out

ucfg = conf("user.toml", account_id="0123abcd", enabled="true")
rc, uout, uerr = render_out(ucfg)
U = split_units(uout)
check("render succeeds with all six units", rc == 0 and list(U) == ALL, (rc, list(U), uerr[-300:]))
check("render says the unit directory on stderr, one line", uerr.startswith("# user units: ") and "systemctl --user" in uerr and "no sudo" in uerr and uerr.count("\n") == 1, uerr[-300:])
check("no User= or Group= line in any unit", not re.search(r"(?m)^(User|Group)=", uout), re.findall(r"(?m)^(?:User|Group)=.*", uout))
check("no multi-user.target anywhere", "multi-user.target" not in uout)
check("stackshot.service and the reload path are wanted by default.target",
      all("\nWantedBy=default.target\n" in U.get(n, "") for n in ("stackshot.service", "stackshot-reload.path")), {n: U.get(n, "")[-80:] for n in ("stackshot.service", "stackshot-reload.path")})
check("no Wants=network-online.target (the user manager has none to pull in)", "Wants=network-online.target" not in uout)
check("the reload service reloads the server and anchor-hub with systemctl --user, never restarts them",
      re.findall(r"(?m)^ExecStart=.*systemctl.*", U.get("stackshot-reload.service", "")) == ["ExecStart=/usr/bin/systemctl --user reload stackshot.service",
                                                                                     "ExecStart=-/usr/bin/systemctl --user reload anchor-hub.service"]
      and " restart " not in U.get("stackshot-reload.service", ""), U.get("stackshot-reload.service"))
check("the reload path watches the config file and nothing else (code is deploy.sh's)",
      re.findall(r"(?m)^PathChanged=.*", U.get("stackshot-reload.path", "")) == [f"PathChanged={os.path.realpath(ucfg)}"], re.findall(r"(?m)^PathChanged=.*", U.get("stackshot-reload.path", "")))
check("the server and anchor-hub take the reload as SIGHUP", all("\nExecReload=/bin/kill -HUP $MAINPID\n" in U.get(n, "") for n in ("stackshot.service", "anchor-hub.service")),
      {n: U.get(n, "") for n in ("stackshot.service", "anchor-hub.service")})
check("every systemctl call in the units carries --user", all(re.match(r"ExecStart=-?/usr/bin/systemctl --user ", l) for l in uout.splitlines() if "systemctl " in l and not l.startswith("#")),
      [l for l in uout.splitlines() if "systemctl " in l])
S_ = re.escape(STACK)
for unit, rx in (("stackshot.service", r"ExecStart=\S+ run --project " + S_ + r" --locked --extra server stackshot server"),
                 ("anchor-hub.service", r"ExecStart=\S+ run --project " + S_ + r" --locked --extra anchor-hub stackshot anchor-hub"),
                 ("stackshot-puller.service", r"ExecStart=/usr/bin/python3 " + S_ + r"/stackshot/fleet/puller\.py")):
    check(f"{unit} starts the package's program (the locked project environment for the two with an extra, the bare python3 for the puller)",
          len(re.findall(r"(?m)^" + rx + "$", U.get(unit, ""))) == 1, re.findall(r"(?m)^ExecStart=.*", U.get(unit, "")))
check("no unit starts a root script or a uv --script: every Exec line names the package", not re.search(r"(?m)^Exec\w*=.*(--script|" + S_ + r"/[\w-]+\.py)", uout),
      re.findall(r"(?m)^Exec\w*=.*(?:--script|" + S_ + r"/[\w-]+\.py).*", uout))
check("the server units keep the header the user-scope rendering always had (an upgrade reports them unchanged)",
      all(U.get(n, "").split("\n", 1)[0] == f'# Rendered by install.sh from units/{n}.in for the user manager ([units] scope = "user") — edit the template, not this file.' for n in SERVER), [U.get(n, "").split("\n", 1)[0] for n in SERVER])
check("the puller and anchor-hub keep their plain header",
      all(U.get(n, "").split("\n", 1)[0] == f"# Rendered by install.sh from units/{n}.in — edit the template, not this file." for n in ("anchor-hub.service", "stackshot-puller.service")), [U.get(n, "").split("\n", 1)[0] for n in ("anchor-hub.service", "stackshot-puller.service")])
rc, dout, _ = render_out(ucfg, "stackshot.service.d-portal-sync.conf")
check("the drop-in renders for the user manager, pulls in the portal sync and calls no systemctl",
      rc == 0 and "for the user manager" in dout and "\nWants=stackshot-portal-sync.service" in dout and "systemctl" not in dout, dout)

# every unit is the plain substitution of its template: nothing is rewritten between the template and the installed file
def reference(name, cfg, times=("05:00",)):
    t = pathlib.Path(STACK, "units", name + ".in").read_text(encoding="utf-8")
    t = "".join("".join(l.replace("@AUDIT_AT@", x) for x in times) if "@AUDIT_AT@" in l else l for l in t.splitlines(keepends=True))   # one line per time of [audit] at
    uv = shutil.which("uv", path=ENV["PATH"]) or os.path.expanduser("~/.local/bin/uv")
    for k, v in (("@CHECKOUT@", STACK), ("@CONFIG@", cfg), ("@HOME@", os.environ["HOME"]), ("@UV@", uv), ("@PORT@", "8020"), ("@TZ@", "UTC"), ("@AUDIT_PROJECT@", "ops/example-service")):
        t = t.replace(k, v)
    head = (f'# Rendered by install.sh from units/{name}.in for the user manager ([units] scope = "user") — edit the template, not this file.\n'
            if name in SERVER + ["stackshot.service.d-portal-sync.conf"] else f"# Rendered by install.sh from units/{name}.in — edit the template, not this file.\n")
    return head + t
ucfg_real = os.path.realpath(ucfg)
for n in ALL + ["stackshot.service.d-portal-sync.conf"]:
    rc, one, _ = render_out(ucfg, n)
    check(f"{n} is the plain substitution of its template", rc == 0 and one == reference(n, ucfg_real), one[:300])

# ---- a config from before the keys at their one value are accepted silently, any removed value is refused with one line each
rc, nout, nerr = render_out(conf("oldscope.toml", scope="user"), "stackshot.service")
check('[units] scope = "user" still in the file: accepted without a word', rc == 0 and "for the user manager" in nout and nerr.startswith("# user units: ") and nerr.count("\n") == 1, (rc, nerr[-200:]))
rc, _, berr = render_out(conf("sysscope.toml", scope="system"))
check('[units] scope = "system": refused with the line naming the removal and the way over', rc != 0 and "removed; " in berr and '[units] scope = "system"' in berr
      and "main/INSTALL.md#an-instance-installed-in-the-system-scope" in berr and berr.count("removed; ") == 1, berr[-500:])
rc, _, berr = render_out(conf("bad.toml", scope="sytem"))
check("an unknown scope is refused too, never guessed", rc != 0 and "removed; " in berr and "sytem" in berr, berr[-300:])
for key, bad, keep in (("reads", "checkout", "api"), ("sessions", "both", "client"), ("delivery", "push", "inbox"), ("liveness", "ssh", "puller")):
    rc, _, berr = render_out(conf(f"legacy-{key}.toml", client={key: bad}))
    check(f'[client] {key} = "{bad}": refused, naming "{keep}" as the one value left', rc != 0 and f'[client] {key} = "{bad}"' in berr and f'"{keep}" is the one value left' in berr
          and f'set {key} = "{keep}" or drop the line' in berr and berr.count("removed; ") == 1, berr[-500:])
rc, kout, kerr = render_out(conf("kept.toml", client={"reads": "api", "sessions": "client", "delivery": "inbox", "liveness": "puller"}), "stackshot.service")
check("the four [client] keys at their one value: accepted without a word", rc == 0 and "for the user manager" in kout and kerr.count("\n") == 1, kerr)
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/core/config.py"), "check"], capture_output=True, text=True, env={**ENV, "STACKSHOT_CONFIG": conf("multi.toml", scope="system", client={"delivery": "push"})})
check("config.py check: one line per removed mode in the file, exit 1", r.returncode == 1 and r.stderr.count("removed; ") == 2 and r.stdout == "", r.stderr[-400:])
check("render never called sudo", not (T / "sudo-called").exists())

# ---- install.sh units in user scope, on a temp HOME, systemctl stubbed: no sudo, everything through the user manager
UH = T / "uhome"; UH.mkdir()
(T / "sbin").mkdir()
# systemctl: logs each call and succeeds; is-enabled / is-active fail while the file `other-off` exists (the other scope's unit disabled)
(T / "sbin/systemctl").write_text(f'''#!/bin/sh
echo "$*" >> {tmp}/systemctl.log
# the environment the user manager gives stackshot.service: carries the standby switch while the file `standby-env` exists (the drop-in docs/read-only-standby.md names)
# and the EnvironmentFile= lines the file `envfiles` holds (systemd's own form: `<path> (ignore_errors=no)`, one per line)
case "$*" in *"show stackshot.service -p EnvironmentFiles"*) [ -e {tmp}/envfiles ] && cat {tmp}/envfiles; exit 0 ;; esac
case "$*" in *"show stackshot.service"*) if [ -e {tmp}/standby-env ]; then echo "PATH=/usr/bin $(cat {tmp}/standby-env)"; fi; exit 0 ;; esac
# the start limit of stackshot-minute.service, as systemd keeps it: while the file `tripped` exists the unit is failed, a restart is refused until reset-failed has cleared the count, and reset-failed on a unit that is not
# failed exits 1 ("Unit ... not loaded"), as the real one does
case "$*" in *reset-failed*stackshot-minute*) if [ -e {tmp}/tripped ]; then rm -f {tmp}/tripped; else echo "Failed to reset failed state of unit stackshot-minute.service: Unit stackshot-minute.service not loaded." >&2; exit 1; fi ;; *restart*stackshot-minute*) if [ -e {tmp}/tripped ]; then echo "Start request repeated too quickly." >&2; exit 1; fi ;; esac
# a minute unit that cannot be stopped: while the file `minute-stuck` exists `disable --now`, `stop` and `disable` for it fail and is-active says what the file holds (active when it is empty); with `minute-half` only `disable --now` and `stop` fail and the unit is inactive
case "$*" in *disable*--now*stackshot-minute*|*stop*stackshot-minute*) if [ -e {tmp}/minute-stuck ] || [ -e {tmp}/minute-half ]; then echo "Failed to stop stackshot-minute.service: Access denied" >&2; exit 1; fi ;; esac
case "$*" in *disable*stackshot-minute*) if [ -e {tmp}/minute-stuck ]; then echo "Failed to disable unit: Access denied" >&2; exit 1; fi ;; esac
case "$*" in *is-active*stackshot-minute*) if [ -e {tmp}/minute-stuck ]; then st="$(cat {tmp}/minute-stuck)"; echo "${{st:-active}}"; exit 0; elif [ -e {tmp}/minute-half ]; then echo inactive; exit 3; fi ;; esac
case "$*" in *is-enabled*|*is-active*) [ -e {tmp}/other-off ] && exit 1 ;; esac
exit 0
'''); (T / "sbin/systemctl").chmod(0o755)
# loginctl: Linger as the file `linger` says; enable-linger succeeds (and flips it) only while the file `linger-may` exists
(T / "sbin/loginctl").write_text(f'''#!/bin/sh
echo "$*" >> {tmp}/loginctl.log
case "$*" in
  show-user*) cat {tmp}/linger ;;
  *enable-linger*) [ -f {tmp}/linger-may ] || exit 1; echo yes > {tmp}/linger ;;
esac
'''); (T / "sbin/loginctl").chmod(0o755); (T / "linger").write_text("yes\n")
UENV = {**ENV, "HOME": str(UH), "PATH": f"{tmp}/sbin:{tmp}/bin:" + os.environ.get("PATH", ""),
        "STACKSHOT_SYSTEM_UNIT_DIR": f"{tmp}/etc-systemd"}      # this box's own /etc/systemd/system is not the test's
def units(cfg, *extra, env=UENV):
    (T / "systemctl.log").unlink(missing_ok=True)
    r = subprocess.run([os.path.join(STACK, "install.sh"), "units", "--config", cfg, *extra], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    calls = (T / "systemctl.log").read_text().splitlines() if (T / "systemctl.log").exists() else []
    return r.returncode, r.stdout + r.stderr, calls
rc, out, calls = units(ucfg)
ud = UH / ".config/systemd/user"
check("units (user): exits 0 and names the unit directory", rc == 0 and "user units: " in out and "systemctl --user, no sudo" in out, out[-800:])
want = ["stackshot.service", "stackshot-reload.service", "stackshot-reload.path", "stackshot-portal-sync.service", "anchor-hub.service", "stackshot-puller.service"]
check("units (user): every unit and the drop-in under ~/.config/systemd/user", all((ud / n).is_file() for n in want) and (ud / "stackshot.service.d/portal-sync.conf").is_file(),
      sorted(str(p.relative_to(ud)) for p in ud.rglob("*") if p.is_file()) if ud.exists() else "missing")
rc_r, u_all, _ = render_out(ucfg, "stackshot.service", env=UENV)
check("units (user): what it installs is what render prints", (ud / "stackshot.service").read_text() == u_all, u_all[:200])
check("units (user): every systemctl call carries --user", calls and all(c.startswith("--user ") for c in calls), calls)
check("units (user): daemon-reload, and the server and the reload path enabled", "--user daemon-reload" in calls and "--user enable --quiet stackshot.service stackshot-reload.path" in calls, calls)
check("units (user): sudo never called", not (T / "sudo-called").exists())
rc, out, calls = units(ucfg)
check("units (user) twice: everything unchanged the second time", rc == 0 and "installed" not in out.replace("not installed", "") and out.count(": unchanged") == 7, out[-800:])
rc, out, calls = units(ucfg, "--start")
check("units (user) --start: the server, the reload path, anchor-hub and the puller restarted through the user manager",
      rc == 0 and all(f"--user restart {n}" in calls for n in ("stackshot.service", "stackshot-reload.path", "anchor-hub.service", "stackshot-puller.service")), (calls, out[-400:]))
(ud / "stackshot.service").write_text("stale\n")
rc, out, calls = units(ucfg, "--restart")
check("units (user) --restart: a changed server unit is restarted with systemctl --user", rc == 0 and "--user restart stackshot.service" in calls and all(c.startswith("--user ") for c in calls), (calls, out[-400:]))
rc, out, calls = units(conf("user-off.toml"), env={**UENV, "HOME": str(T / "uhome2")})
check("units (user), portal off: the portal unit and drop-in skipped, nothing under /etc asked for", rc == 0 and "skipped ([portal] account_id is empty)" in out
      and not (T / "uhome2/.config/systemd/user/stackshot-portal-sync.service").exists(), out[-500:])
check("units (user): sudo still never called", not (T / "sudo-called").exists())
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", conf("sysscope2.toml", scope="system")], capture_output=True, text=True, env={**UENV, "HOME": str(T / "uhome4")}, stdin=subprocess.DEVNULL)
check('puller with a config that still says scope = "system": refused before installing anything, no sudo', r.returncode != 0 and "removed; " in r.stderr
      and not (T / "uhome4/.config/systemd/user").exists() and not (T / "sudo-called").exists(), r.stdout + r.stderr)

# ---- lingering: the user units need it in both scopes, so units and puller see to it
check("lingering on: units says so", "lingering: on for" in out, out[-600:])
(T / "linger").write_text("no\n"); (T / "linger-may").write_text("")
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", ucfg], capture_output=True, text=True, env={**UENV, "HOME": str(T / "uhome5")}, stdin=subprocess.DEVNULL)
lg = (T / "loginctl.log").read_text()
check("lingering off but the user may: puller switches it on itself, without a password prompt", r.returncode == 0 and "lingering: enabled for" in r.stdout
      and "--no-ask-password enable-linger" in lg and (T / "linger").read_text().strip() == "yes" and not (T / "sudo-called").exists(), (r.stdout + r.stderr)[-500:])
(T / "linger").write_text("no\n"); (T / "linger-may").unlink()
rc, out, calls = units(ucfg, env={**UENV, "HOME": str(T / "uhome6")})
sl = (T / "sudo.log").read_text().splitlines() if (T / "sudo.log").exists() else []
check("lingering off and not allowed: units still installs, exits 0 and warns with the root command", rc == 0 and "WARNING: lingering is off for" in out
      and "sudo loginctl enable-linger" in out and (T / "uhome6/.config/systemd/user/stackshot.service").is_file(), out[-600:])
check("…having tried sudo only non-interactively (sudo -n loginctl enable-linger)", any(l.startswith("-n loginctl enable-linger") for l in sl) and all(l.startswith("-n ") for l in sl), sl)
(T / "sudo-called").unlink(missing_ok=True); (T / "sudo.log").unlink(missing_ok=True); (T / "linger").write_text("yes\n")
(T / "uhome7/.config/systemd/user").mkdir(parents=True)
units(ucfg, env={**UENV, "HOME": str(T / "uhome7")}); (T / "uhome7/.config/systemd/user/stackshot.service").write_text("stale\n")
rc, out, calls = units(ucfg, "--quiet-hint", env={**UENV, "HOME": str(T / "uhome7")})
check("--quiet-hint: a changed unit is installed without the 'changed, not restarted' hint", rc == 0 and "stackshot.service: installed" in out and "changed, not restarted" not in out, out[-500:])
rc, out, calls = units(ucfg, env={**UENV, "HOME": str(T / "uhome7")}); (T / "uhome7/.config/systemd/user/stackshot.service").write_text("stale\n")
rc, out, calls = units(ucfg, env={**UENV, "HOME": str(T / "uhome7")})
check("…and without it the hint is there", "changed, not restarted: stackshot.service" in out, out[-300:])
noenv = {k: v for k, v in ENV.items() if k != "USER"}
r = subprocess.run(["env", "-u", "USER", os.path.join(STACK, "install.sh"), "render", "stackshot.service", "--config", ucfg], capture_output=True, text=True, env=noenv)
check("USER unset: render still works (loginctl needs USER; the units carry no User= line)", r.returncode == 0 and "\nUser=" not in r.stdout and "unbound variable" not in r.stderr, (r.stdout + r.stderr)[-300:])

# ---- a stackshot.service of the removed system scope: refused while it is enabled or running, not a word once it is disabled and stopped
(T / "etc-systemd").mkdir(); (T / "etc-systemd/stackshot.service").write_text("[Unit]\n")
rc, out, calls = units(ucfg, env={**UENV, "HOME": str(T / "uhome8")})
check("system-scope unit enabled or running: units refuses, naming the move", rc != 0 and "refused:" in out and "system scope" in out
      and "main/INSTALL.md#an-instance-installed-in-the-system-scope" in out and "race for port" in out, out[-500:])
check("…before installing anything, having read the system manager without sudo", not (T / "uhome8/.config/systemd/user").exists() and "is-enabled -q stackshot.service" in calls
      and not any("daemon-reload" in c or "enable --quiet" in c for c in calls) and not (T / "sudo-called").exists(), calls)
(T / "other-off").touch()
rc, out, calls = units(ucfg, env={**UENV, "HOME": str(T / "uhome8")})
check("system-scope unit disabled and stopped: installs, not a word about it", rc == 0 and "WARNING" not in out and "scope" not in out
      and (T / "uhome8/.config/systemd/user/stackshot.service").is_file(), out[-500:])
(T / "other-off").unlink(); (T / "etc-systemd/stackshot.service").unlink()

# ---- the audit's timer pair: only with [audit] enabled = true; off again → a pair installed earlier is disabled and removed
AUD = ["stackshot-audit.service", "stackshot-audit.timer"]
rc, units_, out = render(conf("aud-off.toml"))
check("audit off (the example's default): no audit units rendered", rc == 0 and not set(AUD) & set(units_), units_)
rc, units_, out = render(conf("aud-on.toml", audit="true"))
check("audit on: the service and the timer join, last", rc == 0 and units_ == BASE + ["stackshot-puller.service"] + AUD, units_)
acfg = conf("aud-at.toml", audit="true", at="06:30", tz="Asia/Dubai")
rc, tout, _ = render_out(acfg, "stackshot-audit.timer")
check("the timer: OnCalendar from [audit] at in the instance timezone, persistent, naming its service",
      rc == 0 and "\nOnCalendar=*-*-* 06:30:00 Asia/Dubai\n" in tout and "\nPersistent=true\n" in tout and "\nUnit=stackshot-audit.service\n" in tout
      and "\nWantedBy=timers.target\n" in tout and tout.startswith("# Rendered by install.sh from units/stackshot-audit.timer.in — edit the template"), tout)
rc, tout, _ = render_out(conf("aud-two.toml", audit="true", at=["05:00", "20:00"], tz="Asia/Dubai"), "stackshot-audit.timer")
check("the timer, two times: one OnCalendar line each, in time order, in the instance timezone, the rest as before",
      rc == 0 and [l for l in tout.splitlines() if l.startswith("OnCalendar=")] == ["OnCalendar=*-*-* 05:00:00 Asia/Dubai", "OnCalendar=*-*-* 20:00:00 Asia/Dubai"]
      and "\nPersistent=true\n" in tout and "\nUnit=stackshot-audit.service\n" in tout and "@AUDIT_AT@" not in tout, tout)
rc, tout, _ = render_out(conf("aud-two-rev.toml", audit="true", at=["20:00", "5:00", "20:00", "late"], tz="Asia/Dubai"), "stackshot-audit.timer")
check("the timer, a list out of order with a repeat and a bad entry: sorted, once each, the bad one dropped",
      rc == 0 and [l for l in tout.splitlines() if l.startswith("OnCalendar=")] == ["OnCalendar=*-*-* 05:00:00 Asia/Dubai", "OnCalendar=*-*-* 20:00:00 Asia/Dubai"], tout)
rc, tout, _ = render_out(conf("aud-one-list.toml", audit="true", at=["06:30"], tz="Asia/Dubai"), "stackshot-audit.timer")
check("the timer, a list of one: the single line a string gives", rc == 0 and [l for l in tout.splitlines() if l.startswith("OnCalendar=")] == ["OnCalendar=*-*-* 06:30:00 Asia/Dubai"], tout)
rc, tout, _ = render_out(conf("aud-ex.toml", audit="true", tz="Asia/Dubai"), "stackshot-audit.timer")
check("the timer from the shipped example: 05:00 and 20:00", rc == 0 and [l for l in tout.splitlines() if l.startswith("OnCalendar=")] == ["OnCalendar=*-*-* 05:00:00 Asia/Dubai", "OnCalendar=*-*-* 20:00:00 Asia/Dubai"], tout)
rc, tout, _ = render_out(conf("aud-badlist.toml", audit="true", at=["25:99", "x"]), "stackshot-audit.timer")
check("the timer, a list with no time of day in it: 05:00", rc == 0 and [l for l in tout.splitlines() if l.startswith("OnCalendar=")] == ["OnCalendar=*-*-* 05:00:00 UTC"], tout)
rc, sout, _ = render_out(conf("aud-svc.toml", audit="true"), "stackshot-audit.service")
lines = sout.splitlines()
check("the service: the rulebook scan is ExecStartPost, after ExecStart (the run), and there is no ExecStartPre",
      rc == 0 and not any(l.startswith("ExecStartPre=") for l in lines) and sum(l.startswith("ExecStartPost=") and "stackshot.tools.rulebook_scan run" in l for l in lines) == 1
      and [i for i, l in enumerate(lines) if l.startswith("ExecStart=")][0] < [i for i, l in enumerate(lines) if l.startswith("ExecStartPost=")][0]
      and any(l.startswith("ExecStartPost=-/usr/bin/timeout 300 ") for l in lines), sout)
rc, tout, _ = render_out(conf("aud-bad.toml", audit="true", at="25:99"), "stackshot-audit.timer")
check("[audit] at that is not a time of day: the timer keeps 05:00", rc == 0 and "\nOnCalendar=*-*-* 05:00:00 UTC\n" in tout, tout)
rc, sout, _ = render_out(acfg, "stackshot-audit.service")
svc = pathlib.Path(STACK, "units/stackshot.service.in").read_text(encoding="utf-8")
same = [l for l in svc.splitlines() if l.startswith(("WorkingDirectory=", "Environment="))]
check("the service: a oneshot running `stackshot audit cue scheduled` with the server unit's working directory and environment lines",
      rc == 0 and "\nType=oneshot\n" in sout and re.search(r"(?m)^ExecStart=\S+ run --project " + re.escape(STACK) + r" --locked stackshot audit cue scheduled$", sout)
      and all(re.sub("@[A-Z_]+@", "", l).split("=")[0] in sout for l in same) and "\nWorkingDirectory=" + STACK + "\n" in sout
      and "\nEnvironment=STACKSHOT_CONFIG=" + os.path.realpath(acfg) + "\n" in sout and "[Install]" not in sout, sout)
check("the service carries X-Project=ops/example-service (the example's [audit] project) once, in [Unit] (sala job check reports no-project without it)",
      rc == 0 and len(re.findall(r"(?m)^X-Project=", sout)) == 1 and sout.index("\nX-Project=ops/example-service\n") < sout.index("[Service]"), sout)
check("the service carries X-Runs-With=servers once, on the line right after X-Project, in [Unit]",
      rc == 0 and len(re.findall(r"(?m)^X-Runs-With=", sout)) == 1 and re.search(r"(?m)^X-Project=[^\n]*\nX-Runs-With=servers\n", sout) and sout.index("\nX-Runs-With=servers\n") < sout.index("[Service]"), sout)
rc, sout2, _ = render_out(conf("aud-proj.toml", audit="true", project="team/audits"), "stackshot-audit.service")
check("[audit] project is the unit's X-Project", rc == 0 and "\nX-Project=team/audits\n" in sout2 and "@AUDIT_PROJECT@" not in sout2, sout2)
for n in AUD:
    rc, one, _ = render_out(conf("aud-ref.toml", audit="true"), n)
    check(f"{n} is the plain substitution of its template", rc == 0 and one == reference(n, os.path.realpath(str(T / "aud-ref.toml")), ("05:00", "20:00")), one[:300])
AH = {**UENV, "HOME": str(T / "uhome9")}; adir = T / "uhome9/.config/systemd/user"
rc, out, calls = units(conf("aud-u-on.toml", audit="true"), env=AH)
check("units, audit on: both files installed, the timer enabled and started, the service never started",
      rc == 0 and all((adir / n).is_file() for n in AUD) and "--user enable --now --quiet stackshot-audit.timer" in calls
      and not any("stackshot-audit.service" in c for c in calls), (calls, out[-500:]))
rc, out, calls = units(conf("aud-u-on.toml", audit="true"), env=AH)
check("units, audit on, twice: unchanged, the timer not restarted", rc == 0 and "stackshot-audit.timer: unchanged" in out
      and "--user restart stackshot-audit.timer" not in calls, (calls, out[-500:]))
rc, out, calls = units(conf("aud-u-on2.toml", audit="true", at="07:15"), "--restart", env=AH)
check("units, a new [audit] at with --restart: the timer re-armed, the service never restarted",
      rc == 0 and "OnCalendar=*-*-* 07:15:00 UTC" in (adir / "stackshot-audit.timer").read_text() and "--user restart stackshot-audit.timer" in calls
      and not any("restart stackshot-audit.service" in c for c in calls), (calls, out[-500:]))
rc, out, calls = units(conf("aud-u-off.toml", audit="false"), env=AH)
check("units, audit off after on: the timer disabled and stopped, both files removed, said once",
      rc == 0 and "--user disable --now --quiet stackshot-audit.timer" in calls and not any((adir / n).exists() for n in AUD)
      and "disabled and removed ([audit] enabled is not true)" in out and all(c.startswith("--user ") for c in calls), (calls, out[-500:]))
rc, out, calls = units(conf("aud-u-off.toml", audit="false"), env=AH)
check("units, audit off with none installed: skipped, no disable call", rc == 0 and "stackshot-audit.service: skipped ([audit] enabled is not true)" in out
      and not any("stackshot-audit" in c for c in calls), (calls, out[-500:]))
check("the audit pair: sudo never called", not (T / "sudo-called").exists())

# ---- the minute runner's unit: only with [runner] process = "unit", never on a standby; nothing else about the unit set moves
MIN = "stackshot-minute.service"
def mhome(n, **extra): return {**UENV, "HOME": str(T / f"uhome-m{n}"), **extra}      # a home of its own per case: the units installed there are the case's
def mdir(n): return T / f"uhome-m{n}/.config/systemd/user"
def parse_unit(text):
    """a unit's text → {section: {key: [values]}}, comments and blank lines dropped."""
    cur, d = None, {}
    for l in text.splitlines():
        l = l.strip()
        if not l or l.startswith("#"): continue
        m = re.fullmatch(r"\[(\w+)\]", l)
        if m: cur = m.group(1); d[cur] = {}; continue
        k, _, v = l.partition("="); d[cur].setdefault(k, []).append(v)
    return d
def minute_calls(calls): return [c for c in calls if "stackshot-minute" in c]
EXISTING = ["stackshot.service", "stackshot-reload.service", "stackshot-reload.path", "stackshot-portal-sync.service", "anchor-hub.service", "stackshot-puller.service"] + AUD
# the same config file in both modes (the unit text carries its path), so the other units' bytes can be compared
mc = conf("m-cfg.toml", account_id="0123abcd", enabled="true", audit="true")
check("the example's [runner] process is inline", re.search(r'(?m)^process = "inline"', toml) is not None)
rc, before_default, _ = render_out(mc, env=UENV)
before = {n: render_out(mc, n, env=UENV)[1] for n in EXISTING + ["stackshot.service.d-portal-sync.conf"]}
rc, defl, _ = render(mc, env=UENV)
check("inline: the default render lists every other unit and no minute unit", rc == 0 and MIN not in defl and "stackshot-minute" not in before_default
      and defl == SERVER + ["anchor-hub.service", "stackshot-puller.service"] + AUD, defl)
rc, mone, _ = render_out(mc, MIN, env=UENV)
check("inline: the unit renders on request all the same, like any unit named explicitly", rc == 0 and mone.startswith("# Rendered by install.sh from units/stackshot-minute.service.in"), mone[:200])
mc = conf("m-cfg.toml", account_id="0123abcd", enabled="true", audit="true", runner="unit")
rc, after_default, _ = render_out(mc, env=UENV)
rc, mdefl, _ = render(mc, env=UENV)
after = {n: render_out(mc, n, env=UENV)[1] for n in EXISTING + ["stackshot.service.d-portal-sync.conf"]}
check("unit: the default render is the inline one plus the minute unit, last", mdefl == defl + [MIN], mdefl)
check("unit: every other unit renders to the very bytes it has at inline", before == after and all(before.values()), {n: (before[n] == after[n]) for n in before})
check("unit: the default render is the inline text, then the minute unit after its separator line",
      after_default == before_default + f"# ---------------- {MIN}\n" + render_out(mc, MIN, env=UENV)[1] and after_default.startswith(before_default), after_default[-300:])
mt = render_out(mc, MIN, env=UENV)[1]
MP, SP = parse_unit(mt), parse_unit(render_out(mc, "stackshot.service", env=UENV)[1])
mu, ms = MP.get("Unit", {}), MP.get("Service", {})
check("minute unit: the plain substitution of its template, under the plain header", render_out(mc, MIN, env={**UENV, "HOME": os.environ["HOME"]})[1] == reference(MIN, os.path.realpath(mc)) and mt.split("\n", 1)[0] == f"# Rendered by install.sh from units/{MIN}.in — edit the template, not this file.", mt[:300])
check("minute unit: ExecStart is the server's command line with `stackshot minute` in place of `stackshot server` (the locked project environment, the server extra)",
      len(ms.get("ExecStart", [])) == 1 and ms["ExecStart"][0] == SP["Service"]["ExecStart"][0].replace(" stackshot server", " stackshot minute")
      and re.fullmatch(r"\S+ run --project " + re.escape(STACK) + r" --locked --extra server stackshot minute", ms["ExecStart"][0]) is not None, ms.get("ExecStart"))
check("minute unit: STACKSHOT_CONFIG is the instance config, and the working directory and environment lines are the server's own",
      f"STACKSHOT_CONFIG={os.path.realpath(mc)}" in ms.get("Environment", []) and sorted(ms.get("Environment", [])) == sorted(SP["Service"]["Environment"])
      and ms.get("WorkingDirectory") == [STACK] == SP["Service"]["WorkingDirectory"], (ms.get("Environment"), SP["Service"]["Environment"]))
check("minute unit: After=stackshot.service in [Unit]", mu.get("After") == ["stackshot.service"], mu)
check("minute unit: [Unit] holds exactly Description, After, ReloadPropagatedFrom and the two start limit keys: nothing that ties it to the server (Requires, Wants, BindsTo, PartOf, Upholds, Conflicts, StopPropagatedFrom, JoinsNamespaceOf ...), so a restart of the server does not stop it",
      set(mu) == {"Description", "After", "ReloadPropagatedFrom", "StartLimitIntervalSec", "StartLimitBurst"} and not any(k in MP.get("Install", {}) for k in ("RequiredBy", "Alias", "Also")), sorted(mu))
check("minute unit: [Service] holds exactly the keys the unit sets (no ExecStartPre, no Type, no memory cap beyond what the template says)",
      set(ms) == {"WorkingDirectory", "Environment", "ExecStart", "ExecReload", "Restart", "RestartSec", "RestartPreventExitStatus", "KillMode", "TimeoutStopSec", "Nice", "CPUWeight"}, sorted(ms))
check("minute unit: Restart=on-failure, RestartSec=5", ms.get("Restart") == ["on-failure"] and ms.get("RestartSec") == ["5"], ms)
check("minute unit: RestartPreventExitStatus=2 3 4 (no config, setting inline, standby never fix themselves; 1, 5 and 6 retry)", ms.get("RestartPreventExitStatus") == ["2 3 4"], ms)
check("minute unit: ExecReload is SIGHUP to the main process", ms.get("ExecReload") == ["/bin/kill -HUP $MAINPID"], ms)
check("minute unit: KillMode=mixed", ms.get("KillMode") == ["mixed"], ms)
check("minute unit: Nice=10, a lower priority than the server's requests (the point of a process of its own)", ms.get("Nice") == ["10"], ms.get("Nice"))
check("minute unit: CPUWeight=50, under the default weight of 100", ms.get("CPUWeight") == ["50"], ms.get("CPUWeight"))
check("minute unit: no MemoryMax (the runner has no measured peak, and a cap would kill a round that is running)", "MemoryMax" not in ms and "MemoryHigh" not in ms, sorted(ms))
check("minute unit: TimeoutStopSec above the 30 seconds `stackshot minute` waits for a round (at least 45)", len(ms.get("TimeoutStopSec", [])) == 1 and re.fullmatch(r"\d+", ms["TimeoutStopSec"][0]) and int(ms["TimeoutStopSec"][0]) >= 45, ms)
sl_i, sl_b = mu.get("StartLimitIntervalSec", [""])[0], mu.get("StartLimitBurst", [""])[0]
check("minute unit: a start limit in [Unit] that exit 5 at the restart pace reaches well inside the interval (so systemd reports the unit failed instead of retrying forever)",
      sl_i.isdigit() and sl_b.isdigit() and int(sl_b) >= 2 and int(sl_i) > 0 and int(sl_i) > int(sl_b) * int(ms["RestartSec"][0]) * 2
      and "StartLimitIntervalSec" not in ms and "StartLimitBurst" not in ms, (sl_i, sl_b, ms.get("RestartSec")))
check("minute unit: ReloadPropagatedFrom=stackshot.service in [Unit]: the server's config reload reaches it (SIGHUP by ExecReload), while the reload service itself is untouched",
      mu.get("ReloadPropagatedFrom") == ["stackshot.service"] and ms.get("ExecReload") == ["/bin/kill -HUP $MAINPID"], mu)
rl = render_out(mc, "stackshot-reload.service", env=UENV)[1]
check("the reload service still reloads the server and anchor-hub and names no minute unit (at unit as at inline)",
      re.findall(r"(?m)^ExecStart=.*systemctl.*", rl) == ["ExecStart=/usr/bin/systemctl --user reload stackshot.service", "ExecStart=-/usr/bin/systemctl --user reload anchor-hub.service"]
      and "minute" not in rl and rl == before["stackshot-reload.service"], rl)
check("minute unit: [Install] WantedBy=default.target", MP.get("Install", {}).get("WantedBy") == ["default.target"], MP.get("Install"))
tpl = pathlib.Path(STACK, "units", MIN + ".in").read_text(encoding="utf-8")
check("minute unit: a header comment names the unit and how it is installed, and the template carries nothing of one machine (no home folder, host, sala or address)",
      tpl.startswith("# stackshot-minute.service") and "./install.sh units" in tpl.split("[Unit]")[0] and not re.search(r"/home/|/Users/|hp-|sala|@\w+\.(com|ai)", tpl, re.I), tpl[:300])
check("`stackshot minute` is a program of the package", re.search(r'(?m)^    "minute": \("stackshot\.web\.minute"', pathlib.Path(STACK, "stackshot/cli.py").read_text(encoding="utf-8")) is not None)

# install.sh units at inline: nothing new, and said so
IC = conf("m-ic.toml", account_id="0123abcd", enabled="true")      # inline, hub and portal on: the largest set at the default
rc, out, calls = units(IC, env=mhome(1))
got = sorted(p.name for p in mdir(1).iterdir() if p.is_file())
check("units at inline: exactly the unit files it always installed, none of them naming a minute unit", rc == 0 and got == sorted(EXISTING[:6]) and not any("stackshot-minute" in (mdir(1) / n).read_text() for n in got), (rc, got, out[-400:]))
check("units at inline: no systemctl call names the minute unit and none asks the user manager about a standby", not minute_calls(calls) and not any("show stackshot.service" in c for c in calls), calls)
check('units at inline: one skipped line, as the other optional units say', 'stackshot-minute.service: skipped ([runner] process is not "unit")' in out and out.count("stackshot-minute") == 1, out[-500:])
rc, out, calls = units(IC, "--start", env=mhome(1))
check("units --start at inline: the server, the reload path, anchor-hub and the puller started as before and nothing for the minute unit", rc == 0 and not minute_calls(calls)
      and all(f"--user restart {n}" in calls for n in ("stackshot.service", "stackshot-reload.path", "anchor-hub.service", "stackshot-puller.service")), (calls, out[-300:]))
rc, out, calls = units(conf("m-bad.toml", runner="bogus"), env=mhome(11))
check('units with [runner] process = "bogus": read as inline, nothing installed for the minute unit, no standby question asked', rc == 0 and not (mdir(11) / MIN).exists() and not minute_calls(calls)
      and not any("show stackshot.service" in c for c in calls) and 'skipped ([runner] process is not "unit")' in out, (out[-300:], calls))

# at "unit"
UC = conf("m-uc.toml", account_id="0123abcd", enabled="true", runner="unit")
rc, out, calls = units(UC, env=mhome(2))
check("units at unit: the unit is installed, as the render prints it, and every call is the user manager's", rc == 0 and (mdir(2) / MIN).is_file()
      and (mdir(2) / MIN).read_text() == render_out(UC, MIN, env=mhome(2))[1] and f"{MIN}: installed" in out and all(c.startswith("--user ") for c in calls), (out[-500:], calls))
check("units at unit: it is enabled, and neither started nor restarted without --start or --restart", "--user enable --quiet stackshot-minute.service" in calls
      and not any(re.search(r"\b(start|restart|stop)\b.*stackshot-minute", c) for c in calls) and (T / "sudo-called").exists() is False, calls)
rc, out, calls = units(UC, env=mhome(2))
check("units at unit, twice: unchanged the second time", rc == 0 and f"{MIN}: unchanged" in out and "installed" not in out.replace("not installed", ""), out[-500:])
rc, out, calls = units(UC, "--start", env=mhome(2))
i_srv, i_min = (calls.index(f"--user restart {n}") if f"--user restart {n}" in calls else -1 for n in ("stackshot.service", MIN))
check("units --start at unit: the minute unit is restarted through the user manager, after the server, the reload path and anchor-hub", rc == 0 and 0 <= i_srv < i_min
      and calls.index("--user restart stackshot-reload.path") < i_min and calls.index("--user restart anchor-hub.service") < i_min and f"started {MIN}" in out, (calls, out[-300:]))
(mdir(2) / "stackshot.service").write_text("stale\n"); (mdir(2) / MIN).write_text("stale\n")
rc, out, calls = units(UC, "--restart", env=mhome(2))
check("units --restart at unit: a changed minute unit is restarted, after the server's", rc == 0 and calls.index("--user restart stackshot.service") < calls.index(f"--user restart {MIN}"), (calls, out[-300:]))
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", UC], capture_output=True, text=True, env=mhome(3), stdin=subprocess.DEVNULL)
check("the puller verb at unit installs the puller alone, never the minute unit", r.returncode == 0 and not (mdir(3) / MIN).exists() and (mdir(3) / "stackshot-puller.service").is_file(), r.stdout + r.stderr)

# a read-only standby: the environment of the script, or the one the user manager gives stackshot.service
rc, out, calls = units(UC, env=mhome(4, STACKSHOT_READ_ONLY="1"))
check("units at unit on a standby (STACKSHOT_READ_ONLY=1 here): not installed, said so, no call for it", rc == 0 and not (mdir(4) / MIN).exists() and not minute_calls(calls)
      and f'{MIN}: skipped ([runner] process is "unit", but this box is a read-only standby)' in out, (out[-400:], calls))
rc, ldef, _ = render(UC, env=mhome(4, STACKSHOT_READ_ONLY="1"))
check("render at unit on a standby: the minute unit is not in the default list", rc == 0 and MIN not in ldef and ldef, ldef)
(T / "standby-env").write_text("STACKSHOT_READ_ONLY=1")
rc, out, calls = units(UC, env=mhome(5))
check("units at unit on a standby that the user manager's environment for stackshot.service says (a drop-in): not installed, said so", rc == 0 and not (mdir(5) / MIN).exists() and not minute_calls(calls)
      and "read-only standby" in out and any("show stackshot.service" in c for c in calls), (out[-400:], calls))
(T / "standby-env").unlink()
rc, ldef, _ = render(UC, env=mhome(6, STACKSHOT_READ_ONLY="0"))
check("STACKSHOT_READ_ONLY=0 is no standby: the unit is in the default list, last", rc == 0 and ldef[-1:] == [MIN], ldef)
units(UC, env=mhome(7))
rc, out, calls = units(UC, env=mhome(7, STACKSHOT_READ_ONLY="1"))
dn, rm_, rf_ = f"--user disable --now --quiet {MIN}", "--user daemon-reload", f"--user reset-failed {MIN}"
check("a unit installed earlier on a box that is a standby now: stopped and disabled first, then its file removed, said so (a running runner cannot notice, and the server's standby drop-in reaches stackshot.service only)",
      rc == 0 and not (mdir(7) / MIN).exists() and dn in calls and calls.index(dn) < calls.index(rm_) and f"{MIN}: stopped, disabled and removed (this box is a read-only standby: a runner would write the board)" in out
      and not any(re.search(r"\b(start|restart)\b.*stackshot-minute", c) for c in calls), (out[-400:], calls))
check("...the failed state it may leave is cleared after the removal (a unit past its start limit lingers as not-found failed otherwise), and a reset-failed that exits 1 for a unit that is not failed is no failure",
      rf_ in calls and calls.index(rf_) > calls.index(dn) and "FAILED" not in out, (out[-400:], calls))
units(UC, env=mhome(43)); (T / "standby-env").write_text("STACKSHOT_READ_ONLY=1")
rc, out, calls = units(UC, env=mhome(43))
check("...the same when the standby is what the user manager's environment for stackshot.service says (the drop-in)", rc == 0 and not (mdir(43) / MIN).exists() and dn in calls and "read-only standby" in out, (out[-300:], calls))
(T / "standby-env").unlink()
# a standby set by an EnvironmentFile= (systemctl show -p Environment does not list it): the files `-p EnvironmentFiles` names are read, the last STACKSHOT_READ_ONLY= line of a file decides and overrides Environment=
(T / "envf-on").write_text('# comment\nFOO=1\nSTACKSHOT_READ_ONLY=1\n'); (T / "envf-q").write_text('STACKSHOT_READ_ONLY="1"\n'); (T / "envf-off").write_text('STACKSHOT_READ_ONLY=1\nSTACKSHOT_READ_ONLY=0\n')
(T / "envf-cmt").write_text('#STACKSHOT_READ_ONLY=1\n;STACKSHOT_READ_ONLY=1\n'); (T / "envf-long").write_text('STACKSHOT_READ_ONLY=10\n'); (T / "envf-sp").write_text('  STACKSHOT_READ_ONLY=1  \n')
for n_, (listing, who, standby_) in enumerate((
        (f"{T}/envf-on (ignore_errors=no)\n", "a file with STACKSHOT_READ_ONLY=1", True), (f"{T}/envf-q (ignore_errors=yes)\n", "a file with the value in quotes", True),
        (f"{T}/envf-sp (ignore_errors=no)\n", "a file with the line indented and trailing blanks", True),
        (f"{T}/envf-off (ignore_errors=no)\n", "a file whose last line says 0", False), (f"{T}/envf-cmt (ignore_errors=no)\n", "a file that only has it in comments", False),
        (f"{T}/envf-long (ignore_errors=no)\n", "a file with STACKSHOT_READ_ONLY=10", False), (f"{T}/nothing-here (ignore_errors=yes)\n", "a file that is not there", False),
        (f"{T}/envf-off (ignore_errors=no)\n{T}/envf-on (ignore_errors=no)\n", "two files, the later one on", True), (f"{T}/envf-on (ignore_errors=no)\n{T}/envf-off (ignore_errors=no)\n", "two files, the later one off", False)), 50):
    (T / "envfiles").write_text(listing)
    rc, out, calls = units(UC, env=mhome(n_))
    check(f"EnvironmentFile= with {who}: " + ("a standby (the unit is not installed, said so)" if standby_ else "no standby (the unit is installed)"),
          rc == 0 and ((not (mdir(n_) / MIN).exists() and "read-only standby" in out) if standby_ else ((mdir(n_) / MIN).is_file() and "read-only standby" not in out)), (out[-300:], calls))
(T / "envfiles").write_text(f"{T}/envf-off (ignore_errors=no)\n"); (T / "standby-env").write_text("STACKSHOT_READ_ONLY=1")
rc, out, calls = units(UC, env=mhome(60))
check("a file that says STACKSHOT_READ_ONLY=0 overrides Environment=STACKSHOT_READ_ONLY=1 (systemd lets EnvironmentFile= win): no standby", rc == 0 and (mdir(60) / MIN).is_file(), (out[-300:], calls))
(T / "envfiles").write_text(f"{T}/envf-on (ignore_errors=no)\n"); (T / "standby-env").write_text("STACKSHOT_READ_ONLY=0")
rc, out, calls = units(UC, env=mhome(61))
check("a file that says STACKSHOT_READ_ONLY=1 overrides Environment=STACKSHOT_READ_ONLY=0: a standby", rc == 0 and not (mdir(61) / MIN).exists() and "read-only standby" in out, (out[-300:], calls))
(T / "envfiles").unlink(); (T / "standby-env").unlink()
rc, out, calls = units(IC, env=mhome(62))
check("units at inline asks the user manager nothing about EnvironmentFile= either", rc == 0 and not any("show stackshot.service" in c for c in calls), calls)

# flipping back to inline (and a value that is not "unit"): the installed unit is stopped, disabled and removed, as the audit's pair is
units(UC, env=mhome(8))
check("(setup) the unit is there before the flip back", (mdir(8) / MIN).is_file())
rc, out, calls = units(IC, env=mhome(8))
check("units back at inline: the minute unit is disabled and stopped, its file removed, said once", rc == 0 and "--user disable --now --quiet stackshot-minute.service" in calls and not (mdir(8) / MIN).exists()
      and out.count("stackshot-minute.service: stopped, disabled and removed ([runner] process is not \"unit\")") == 1 and all(c.startswith("--user ") for c in calls), (calls, out[-400:]))
check("...and says on that line that the server runs no runner until it is restarted, with the command", re.search(r'(?m)^  stackshot-minute\.service: stopped, disabled and removed .*the server runs no runner until it is restarted: systemctl --user restart stackshot\.service$', out) is not None, out[-400:])
check("...the disable comes before the file goes: the process is stopped while its unit is still known", calls.index("--user disable --now --quiet stackshot-minute.service") < calls.index("--user daemon-reload"), calls)
check("...and a failed state the unit may leave is cleared after the removal: reset-failed comes after the disable, and exits 1 for a unit that is not failed without failing the script", rf_ in calls and calls.index(rf_) > calls.index(dn) and "FAILED" not in out, calls)
rc, out, calls = units(IC, env=mhome(8))
check("units at inline again, none installed: only skipped, no call for it", rc == 0 and not minute_calls(calls) and 'stackshot-minute.service: skipped ([runner] process is not "unit")' in out, (calls, out[-300:]))
# a unit that already tripped its start limit (failed) and goes at inline: its failed state is reset, or it lingers as not-found failed and the user manager reads degraded
units(UC, env=mhome(63)); (T / "tripped").write_text("")
rc, out, calls = units(IC, env=mhome(63))
check("units back at inline, the unit failed (start limit tripped): removed, and reset-failed run after the disable so nothing lingers", rc == 0 and not (mdir(63) / MIN).exists() and not (T / "tripped").exists()
      and rf_ in calls and calls.index(rf_) > calls.index(dn), (rc, calls, out[-300:]))
(T / "tripped").unlink(missing_ok=True)

# C4: a unit that cannot be stopped is never removed while it runs, and the script says so and ends with an error after installing the rest
units(UC, env=mhome(64)); (T / "minute-stuck").write_text("")
rc, out, calls = units(IC, env=mhome(64))
check("units back at inline, the unit cannot be stopped: its file stays, the failure is named on stderr, the exit is nonzero", rc != 0 and (mdir(64) / MIN).is_file() and "FAILED to stop stackshot-minute.service (it is active)" in out
      and "its file is left in place" in out and "stopped, disabled and removed" not in out and f"--user stop {MIN}" in calls, (rc, out[-500:], calls))
check("...the others are installed as usual (the failure ends the script, never stops it half way) and the removal is not claimed", (mdir(64) / "stackshot.service").is_file() and "--user daemon-reload" in calls and f"{MIN}: skipped" not in out, (calls, out[-300:]))
units(UC, env=mhome(66)); rc, out, calls = units(UC, env=mhome(66, STACKSHOT_READ_ONLY="1"))
check("a standby whose unit cannot be stopped: the same, file kept and nonzero exit", rc != 0 and (mdir(66) / MIN).is_file() and "FAILED to stop" in out, (rc, out[-400:]))
# a unit that is still on its way up or down is not stopped either: only "inactive" or "failed" (or not loaded) lets the file go
for i, state in enumerate(("activating", "deactivating", "reloading")):
    units(UC, env=mhome(70 + i)); (T / "minute-stuck").write_text(state)
    rc, out, calls = units(IC, env=mhome(70 + i))
    check(f"units back at inline, the unit cannot be stopped and is {state}: its file stays, the failure names the state, the exit is nonzero", rc != 0 and (mdir(70 + i) / MIN).is_file() and f"FAILED to stop stackshot-minute.service (it is {state})" in out
          and "stopped, disabled and removed" not in out, (rc, out[-400:]))
(T / "minute-stuck").unlink(); (T / "minute-half").write_text("")
units(UC, env=mhome(67)); rc, out, calls = units(IC, env=mhome(67))
check("disable --now fails but the unit is not running after it (a unit that is not loaded): treated as stopped, removed, exit 0", rc == 0 and not (mdir(67) / MIN).exists() and "stopped, disabled and removed" in out and "FAILED" not in out, (rc, out[-400:], calls))
(T / "minute-half").unlink()
# the minute-off verb (deploy.sh's rollback to a commit from before the unit runs it): stopped, disabled and removed whatever the setting says
units(UC, env=mhome(68)); (T / "systemctl.log").unlink(missing_ok=True)
r = subprocess.run([os.path.join(STACK, "install.sh"), "minute-off", "--config", UC], capture_output=True, text=True, env=mhome(68), stdin=subprocess.DEVNULL); calls = (T / "systemctl.log").read_text().splitlines()
check("install.sh minute-off at unit: the unit is stopped, disabled and removed, the manager reloaded after it", r.returncode == 0 and not (mdir(68) / MIN).exists() and dn in calls and "--user daemon-reload" in calls
      and calls.index(dn) < calls.index("--user daemon-reload") and rf_ in calls and "stackshot-minute.service: stopped, disabled and removed" in r.stdout and (mdir(68) / "stackshot.service").is_file(), (r.returncode, r.stdout + r.stderr, calls))
(T / "systemctl.log").unlink(missing_ok=True)
r = subprocess.run([os.path.join(STACK, "install.sh"), "minute-off", "--config", UC], capture_output=True, text=True, env=mhome(68), stdin=subprocess.DEVNULL)
check("install.sh minute-off with no unit installed: says so, exit 0, no stop", r.returncode == 0 and "stackshot-minute.service: not installed" in r.stdout and not minute_calls((T / "systemctl.log").read_text().splitlines()), r.stdout + r.stderr)
units(UC, env=mhome(69)); (T / "minute-stuck").write_text("")
r = subprocess.run([os.path.join(STACK, "install.sh"), "minute-off", "--config", UC], capture_output=True, text=True, env=mhome(69), stdin=subprocess.DEVNULL)
check("install.sh minute-off with a unit that cannot be stopped: its file stays, the failure is named, exit 1", r.returncode == 1 and (mdir(69) / MIN).is_file() and "FAILED to stop stackshot-minute.service" in r.stderr, r.stdout + r.stderr)
(T / "minute-stuck").unlink()
# no systemctl on the PATH (a box without systemd, a stripped cron PATH): with no unit file there is nothing to stop and it says so, exit 0; with the file there it fails closed and says why, the file kept
def nosystemctl_path(dest, path_dirs):
    """A PATH like `path_dirs` with no systemctl: each dir that holds one is replaced by `dest`, which links every other entry of those dirs (the first of a name wins). A name already linked is tested with lexists: a dangling link (a runner lists one in both /bin and /usr/bin) reads as absent through exists(), and the second os.symlink raises FileExistsError."""
    dest.mkdir(exist_ok=True)
    dirs = [d_ for d_ in dict.fromkeys(path_dirs) if d_]
    for d_ in dirs:
        if os.path.isfile(os.path.join(d_, "systemctl")):
            for n_ in os.listdir(d_):
                if n_ != "systemctl" and not os.path.lexists(dest / n_): os.symlink(os.path.join(d_, n_), dest / n_)
    return os.pathsep.join(str(dest) if os.path.isfile(os.path.join(d_, "systemctl")) else d_ for d_ in dirs)
NOSD = T / "nosd"
NOSD_PATH = nosystemctl_path(NOSD, os.environ.get("PATH", "").split(os.pathsep))
# the runner's case: a link whose target does not exist, listed in two PATH dirs that both hold a systemctl (the runner's /bin and /usr/bin both list grub-ntldr-img); a real file of the same name in both, and one only in the second
XD = T / "nosd-x"; XD.mkdir(); xa, xb = XD / "a", XD / "b"; xa.mkdir(); xb.mkdir()
for xd_ in (xa, xb):
    (xd_ / "systemctl").write_text("#!/bin/sh\n"); os.symlink(str(XD / "gone-target"), xd_ / "dangling-tool"); (xd_ / "same-tool").write_text("x\n")
(xb / "only-in-b").write_text("x\n")
try: xpath, xerr = nosystemctl_path(XD / "nosd", [str(xa), str(XD / "plain"), str(xb), str(xa)]), None
except Exception as e_: xpath, xerr = None, repr(e_)
check("the no-systemctl PATH dir is built from two PATH dirs that both list the same dangling link: no error, one link per name (the first), the dir without a systemctl kept in its place, no systemctl",
      xerr is None and sorted(os.listdir(XD / "nosd")) == ["dangling-tool", "only-in-b", "same-tool"] and os.readlink(XD / "nosd" / "dangling-tool") == str(xa / "dangling-tool") and not os.path.exists(XD / "nosd" / "dangling-tool") and os.readlink(XD / "nosd" / "same-tool") == str(xa / "same-tool")
      and xpath == os.pathsep.join((str(XD / "nosd"), str(XD / "plain"), str(XD / "nosd"))), (xerr, xpath, sorted(os.listdir(XD / "nosd")) if (XD / "nosd").exists() else None))
def nosys(n): return {**ENV, "HOME": str(T / f"uhome-m{n}"), "PATH": f"{tmp}/bin:" + NOSD_PATH}
assert shutil.which("systemctl", path=nosys(0)["PATH"]) is None, "the PATH of these cases has no systemctl"
(T / f"uhome-m80").mkdir(); (T / "systemctl.log").unlink(missing_ok=True)
r = subprocess.run([os.path.join(STACK, "install.sh"), "minute-off", "--config", UC], capture_output=True, text=True, env=nosys(80), stdin=subprocess.DEVNULL)
check("install.sh minute-off with no systemctl and no unit file: 'not installed', exit 0 (nothing to stop, so no user manager is needed to say so)", r.returncode == 0 and "stackshot-minute.service: not installed" in r.stdout and "user manager" not in r.stderr, (r.returncode, r.stdout + r.stderr))
units(UC, env=mhome(81))
r = subprocess.run([os.path.join(STACK, "install.sh"), "minute-off", "--config", UC], capture_output=True, text=True, env=nosys(81), stdin=subprocess.DEVNULL)
check("install.sh minute-off with no systemctl and the unit file there: fails closed (exit 1), the file stays, and the message says systemctl is not available (not a user-manager message)",
      r.returncode == 1 and (mdir(81) / MIN).is_file() and "could not be stopped: systemctl is not available" in r.stderr and "user manager" not in r.stderr, (r.returncode, r.stdout + r.stderr))
units(UC, env=mhome(9))
rc, out, calls = units(conf("m-bad2.toml", runner="Inline "), env=mhome(9))
check('units with [runner] process = "Inline " after unit: read as inline (stripped, lowercased), so the unit is removed', rc == 0 and not (mdir(9) / MIN).exists() and "--user disable --now --quiet stackshot-minute.service" in calls, (calls, out[-300:]))
units(UC, env=mhome(10))
rc, out, calls = units(conf("m-case.toml", runner=" UNIT "), env=mhome(10))
check('units with [runner] process = " UNIT ": read as unit (config.py strips and lowercases it), so the unit stays installed', rc == 0 and (mdir(10) / MIN).is_file() and not minute_calls([c for c in calls if "disable" in c]), (calls, out[-300:]))
check("the minute unit's cases: sudo never called", not (T / "sudo-called").exists())

# a standby is exactly STACKSHOT_READ_ONLY=1: a longer value that only starts with 1, or a name that only ends in it, is none, in the script's environment and in the user manager's
for n_, val in enumerate(("10", "1x", "true", "yes", "01", " 1"), 20):
    rc, ldef, _ = render(UC, env=mhome(n_, STACKSHOT_READ_ONLY=val))
    check(f"STACKSHOT_READ_ONLY={val!r} in the script's environment is no standby (only exactly 1 is): the unit is in the default list", rc == 0 and ldef[-1:] == [MIN], ldef)
for n_, val in enumerate(("STACKSHOT_READ_ONLY=10", "STACKSHOT_READ_ONLY=1x", "STACKSHOT_READ_ONLY=0", "XSTACKSHOT_READ_ONLY=1", "STACKSHOT_READ_ONLY=true"), 30):
    (T / "standby-env").write_text(val)
    rc, out, calls = units(UC, env=mhome(n_))
    check(f"{val!r} in the user manager's environment for stackshot.service is no standby: the unit is installed", rc == 0 and (mdir(n_) / MIN).is_file() and "read-only standby" not in out and any("show stackshot.service" in c for c in calls), (out[-300:], calls))
(T / "standby-env").write_text("PATH=/usr/bin STACKSHOT_READ_ONLY=1 LANG=C")
rc, out, calls = units(UC, env=mhome(40))
check("STACKSHOT_READ_ONLY=1 among other variables of the user manager's environment is a standby", rc == 0 and not (mdir(40) / MIN).exists() and "read-only standby" in out, (out[-300:], calls))
(T / "standby-env").unlink()

# the start limit: past it systemd refuses a plain restart, so every path that starts or restarts the unit runs reset-failed first (the stub refuses a restart while `tripped` exists)
units(UC, env=mhome(41))
(T / "tripped").write_text("")
rc, out, calls = units(UC, "--start", env=mhome(41))
rf, rs = f"--user reset-failed {MIN}", f"--user restart {MIN}"
check("units --start, minute unit past its start limit: reset-failed comes right before its restart, the restart works and everything is started", rc == 0 and rf in calls and calls.index(rf) < calls.index(rs)
      and f"started {MIN}" in out and "FAILED" not in out and not (T / "tripped").exists(), (rc, calls, out[-300:]))
check("units --start: reset-failed is asked once, only for the minute unit", [c for c in calls if "reset-failed" in c] == [rf], calls)
(mdir(41) / MIN).write_text("stale\n"); (T / "tripped").write_text("")
rc, out, calls = units(UC, "--restart", env=mhome(41))
check("units --restart, a changed minute unit past its start limit: reset-failed, then the restart, which works", rc == 0 and rf in calls and calls.index(rf) < calls.index(rs) and f"restarted {MIN}" in out and not (T / "tripped").exists(), (rc, calls, out[-300:]))
rc, out, calls = units(UC, env=mhome(41))
check("units alone (no --start, no --restart): no reset-failed and no restart", rc == 0 and not any("reset-failed" in c or "restart" in c for c in calls), calls)
rc, out, calls = units(IC, "--start", env=mhome(42))
check("units --start at inline: no reset-failed for anything", rc == 0 and not any("reset-failed" in c for c in calls), calls)
(T / "tripped").unlink(missing_ok=True)
# ---- the server host: `units` installs the server's units on the box the instance's server runs on and refuses on any other, in one line, before anything is touched
import socket
ME = socket.gethostname()
def hconf(name, deploy=None, box=None, lookup=None):
    t = pathlib.Path(conf(name)).read_text(encoding="utf-8")
    if deploy is not None:
        t, n = re.subn(r'(?m)^deploy_ssh = "[^"]*"', lambda m: f'deploy_ssh = "{deploy}"', t); assert n == 1
    if box is not None:
        t, n = re.subn(r'(?m)^# box = true\b', f'box = {box}', t); assert n == 1
    if lookup is not None:
        assert "\n[hosts]" not in t; t += f'\n[hosts]\nlookup = "{lookup} {{role}}"\n'
    p = T / name; p.write_text(t, encoding="utf-8"); return str(p)
def hhome(n): return {**UENV, "HOME": str(T / f"uhome-h{n}")}
def hdir(n): return T / f"uhome-h{n}/.config/systemd/user"
def untouched(n, calls): return not hdir(n).exists() and all(c.startswith("--user show ") for c in calls) and not (T / "loginctl.log").exists()      # no unit, no systemctl call but the standby question (a read), not even lingering
def refused_line(out): return out.strip().count("\n") == 0 and out.startswith("refused: ")
(T / "loginctl.log").unlink(missing_ok=True)
rc, out, calls = units(hconf("host-other.toml", deploy="host-a.example"), env=hhome(1))
check("units on a box that is not the server host (deploy_ssh names another): exit 1, one line naming that host, this box and --force-host, nothing installed or touched",
      rc == 1 and refused_line(out) and "host-a.example" in out and ME in out and "--force-host" in out and untouched(1, calls), (rc, out[-400:], calls))
for n, dep, who in ((2, ME, "its own name"), (3, ME.split(".")[0].upper(), "its short name in capitals"), (4, f"deploy@{ME.split('.')[0]}", "user@short name"), (5, "127.0.0.1", "a loopback address"), (6, "localhost", "localhost")):
    rc, out, calls = units(hconf(f"host-same{n}.toml", deploy=dep), env=hhome(n))
    check(f"units on the server host (deploy_ssh names this box by {who}): installed", rc == 0 and "refused" not in out and (hdir(n) / "stackshot.service").is_file(), (rc, out[-300:]))
rc, out, calls = units(hconf("host-none.toml"), env=hhome(7))
check("units when the config names no server host (the example's deploy_ssh is empty, [server] box unset): installed, as before", rc == 0 and "refused" not in out and (hdir(7) / "stackshot.service").is_file(), (rc, out[-300:]))
rc, out, calls = units(hconf("host-boxtrue.toml", box="true"), env=hhome(8))
check("units with [server] box = true and no host named: installed", rc == 0 and (hdir(8) / "stackshot.service").is_file(), (rc, out[-300:]))
(T / "loginctl.log").unlink(missing_ok=True)
rc, out, calls = units(hconf("host-boxfalse.toml", box="false"), env=hhome(9))
check("units with [server] box = false (this box was told the server runs elsewhere): exit 1, one line saying so, nothing touched",
      rc == 1 and refused_line(out) and "[server] box = false" in out and ME in out and "--force-host" in out and untouched(9, calls), (rc, out[-400:], calls))
rc, out, calls = units(hconf("host-boxfalse-me.toml", deploy=ME, box="false"), env=hhome(10))
check("units with deploy_ssh naming this box and [server] box = false: the named host wins, installed", rc == 0 and (hdir(10) / "stackshot.service").is_file(), (rc, out[-300:]))
(T / "loginctl.log").unlink(missing_ok=True)
rc, out, calls = units(hconf("host-conflict.toml", deploy="host-a.example", box="true"), env=hhome(11))
check("units with deploy_ssh naming another box and [server] box = true: refused (the named host wins)", rc == 1 and refused_line(out) and not hdir(11).exists(), (rc, out[-300:]))
# a read-only standby keeps today's path, whichever way its switch is set
rc, out, calls = units(hconf("host-standby.toml", deploy="host-a.example"), env={**hhome(12), "STACKSHOT_READ_ONLY": "1"})
check("units on a read-only standby (STACKSHOT_READ_ONLY=1) whose config names another host: installed, not refused", rc == 0 and "refused" not in out and (hdir(12) / "stackshot.service").is_file(), (rc, out[-300:]))
(T / "standby-env").write_text("STACKSHOT_READ_ONLY=1")
rc, out, calls = units(hconf("host-standby2.toml", box="false"), env=hhome(13))
check("units on a standby the user manager's environment for stackshot.service says: installed, not refused", rc == 0 and "refused" not in out and (hdir(13) / "stackshot.service").is_file(), (rc, out[-300:]))
(T / "standby-env").unlink()
rc, out, calls = units(hconf("host-standby3.toml", deploy="host-a.example"), env={**hhome(14), "STACKSHOT_READ_ONLY": "0"})
check("STACKSHOT_READ_ONLY=0 is no standby: refused", rc == 1 and refused_line(out) and not hdir(14).exists(), (rc, out[-300:]))
# --force-host: a deliberate install through
rc, out, calls = units(hconf("host-force.toml", deploy="host-a.example"), "--force-host", env=hhome(15))
check("units --force-host on another box: installed, nothing refused", rc == 0 and "refused" not in out and (hdir(15) / "stackshot.service").is_file() and (hdir(15) / "stackshot-reload.path").is_file(), (rc, out[-300:]))
rc, out, calls = units(hconf("host-force2.toml", box="false"), "--force-host", "--start", env=hhome(16))
check("units --force-host with [server] box = false, and --start: installed and started", rc == 0 and "--user restart stackshot.service" in calls, (rc, out[-300:], calls))
# the other verbs are not checked: they install no server unit
rc, ren, _ = render(hconf("host-render.toml", deploy="host-a.example"), env=hhome(17))
check("render on another box: not refused", rc == 0 and ren, (rc, ren))
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", str(T / "host-render.toml")], capture_output=True, text=True, env=hhome(18), stdin=subprocess.DEVNULL)
check("puller on another box: installs the puller alone, not refused", r.returncode == 0 and "refused" not in r.stdout + r.stderr and (hdir(18) / "stackshot-puller.service").is_file() and not (hdir(18) / "stackshot.service").exists(), (r.returncode, r.stdout[-300:], r.stderr[-300:]))
# a host word is looked up per [hosts]: the lookup names this box, another box, or there is none
for n, say, want_ok in ((19, ME, True), (20, "host-a.example", False)):
    lk = T / f"where-{n}"; lk.write_text(f"#!/bin/sh\necho {say}\n"); lk.chmod(0o755)
    rc, out, calls = units(hconf(f"host-word{n}.toml", deploy="host:server", lookup=str(lk)), env=hhome(n))
    check(f"deploy_ssh as a host word whose lookup names {'this box' if want_ok else 'another box'}: " + ("installed" if want_ok else "refused, naming that host"),
          (rc == 0 and (hdir(n) / "stackshot.service").is_file()) if want_ok else (rc == 1 and refused_line(out) and say in out and not hdir(n).exists()), (rc, out[-300:]))
rc, out, calls = units(hconf("host-word21.toml", deploy="host:server"), env=hhome(21))
check("deploy_ssh as a host word with no lookup: the word stays as written, so it is another host: refused, naming the word and saying the lookup did not resolve",
      rc == 1 and refused_line(out) and "host:server" in out and "did not resolve" in out and not hdir(21).exists(), (rc, out[-300:]))
lk = T / "where-fail"; lk.write_text("#!/bin/sh\nexit 1\n"); lk.chmod(0o755)
rc, out, calls = units(hconf("host-word22.toml", deploy="host:server", lookup=str(lk)), env=hhome(22))
check("deploy_ssh as a host word whose lookup fails: refused, and the line says the lookup did not resolve", rc == 1 and refused_line(out) and "did not resolve" in out and not hdir(22).exists(), (rc, out[-300:]))
rc, out, calls = units(hconf("host-other2.toml", deploy="host-a.example"), env=hhome(23))
check("the refusal for another host says an alias or an address of this box is not recognized, and to name the box by its hostname", rc == 1 and "not recognized" in out and "hostname" in out, out[-400:])
# a check that cannot run (the config read behind it fails) refuses nothing: the install goes on, and the failure stays out of the output (a python3 that fails for that one call, and is the real one for the others)
(T / "pyfail").mkdir()
(T / "pyfail/python3").write_text('#!/bin/sh\ncase "$*" in *server_host_refusal*) echo "Traceback: the config could not be read" >&2; exit 1 ;; esac\nexec ' + shutil.which("python3") + ' "$@"\n'); (T / "pyfail/python3").chmod(0o755)
rc, out, calls = units(hconf("host-readfail.toml", deploy="host-a.example"), env={**hhome(24), "PATH": f"{T}/pyfail:" + hhome(24)["PATH"]})
check("units when the config read behind the server-host check fails: the check refuses nothing (fails open), installs, and prints none of the failure",
      rc == 0 and "refused" not in out and "Traceback" not in out and (hdir(24) / "stackshot.service").is_file(), (rc, out[-300:]))
r = subprocess.run([os.path.join(STACK, "install.sh")], capture_output=True, text=True, env=ENV)
check("the usage text names --force-host and the server host rule", "--force-host" in r.stdout and "server host" in r.stdout and "deploy_ssh" in r.stdout, r.stdout[:600])
# the usage lines of the header: the description starts in the same column on each
usage = [l for l in pathlib.Path(STACK, "install.sh").read_text(encoding="utf-8").splitlines() if re.match(r"#   \./install\.sh (units|puller|render)\b", l)]
cols = {len(re.match(r"#   \./install\.sh (?:units|puller|render(?: \[name\])?) +", l).group(0)) for l in usage}
check("the usage lines of install.sh (units, puller, render) start their text in one column", len(usage) == 3 and len(cols) == 1, (usage, cols))

r = subprocess.run([os.path.join(STACK, "install.sh")], capture_output=True, text=True, env=ENV)
check("the usage text lists the minute unit and its condition", r.returncode == 2 and "stackshot-minute.service only when [runner] process = \"unit\"" in r.stdout and "standby" in r.stdout, r.stdout[:1500])
check("the usage text names the minute-off verb and says why a standby removes the unit (a running process reads the standby switch at its start only)", "./install.sh minute-off" in r.stdout and "cannot notice" in r.stdout and "exits 1" in r.stdout, r.stdout[:2500])
r = subprocess.run([os.path.join(STACK, "install.sh")], capture_output=True, text=True, env=ENV)
check("no verb: the usage text, exit 2", r.returncode == 2 and "--start" in r.stdout and "account_id" in r.stdout and "set -euo" not in r.stdout, r.stdout[-300:])
check("the usage text explains the user manager and lingering", "systemctl --user" in r.stdout and "enable-linger" in r.stdout, r.stdout[-300:])

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": install scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
