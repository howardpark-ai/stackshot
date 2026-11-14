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

def conf(name, account_id="", enabled="false", scope=None, client=None, audit=None, at=None, tz=None, project=None):
    t, n1 = re.subn(r'(?m)^account_id = "[^"]*"', f'account_id = "{account_id}"', toml)
    t, n2 = re.subn(r'(?m)^(\[anchor_hub\][^\n]*\n)enabled = (true|false)', rf'\g<1>enabled = {enabled}', t)
    assert n1 == 1 and n2 == 1, (n1, n2)
    if audit is not None:                    # [audit] enabled
        t, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = (true|false)', rf'\g<1>enabled = {audit}', t); assert n == 1
    if at is not None:
        lit = "[" + ", ".join(f'"{x}"' for x in at) + "]" if isinstance(at, list) else f'"{at}"'    # a string or a list of them, as the config has it
        t, n = re.subn(r'(?m)^at = (?:"[^"]*"|\[[^\]\n]*\])', lambda m: f'at = {lit}', t); assert n == 1
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

r = subprocess.run([os.path.join(STACK, "install.sh")], capture_output=True, text=True, env=ENV)
check("no verb: the usage text, exit 2", r.returncode == 2 and "--start" in r.stdout and "account_id" in r.stdout and "set -euo" not in r.stdout, r.stdout[-300:])
check("the usage text explains the user manager and lingering", "systemctl --user" in r.stdout and "enable-linger" in r.stdout, r.stdout[-300:])

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": install scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
