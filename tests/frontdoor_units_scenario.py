"""Scenario test for the front door's units (units/stackshot-{frontdoor,signin,splitter}.service.in, units/stackshot-splitter.Caddyfile.in), the part of
install.sh that renders them, and the check systemd runs before every start of the splitter (stackshot/frontdoor/splitter.py). No real systemd, no real sudo,
nothing outside a temp dir: HOME is a temp folder, systemctl, loginctl and sudo are stubs.

Covers: a config with none of the front door's tables renders and installs no front door file and names none; each table brings its own unit; `units`
installs the files and never enables or starts one, --start included; --restart and --start restart one whose file changed only when it runs already, once;
the splitter is neither rendered nor installed while [server] port gives the board its port, without the tables it points at, or with another MCP path, an
installed one stays and is said to; the unit files' lines that keep a restart with the board and a deliberate start; the rendered ExecStartPre line, run with
the system's python3: passes only for the values the config still says and a Caddy of 2.11.6 or later, and refuses after the config gave the port back (a reboot
after an undo); the Caddyfile's lines. With a `caddy` on PATH the rendered Caddyfile is run against stand-in services: client identity headers are removed,
the token check path is refused, the MCP path is checked and goes to the front door, everything else to the board, on the loopback address only.

    tests/run-suite frontdoor_units        → exit 0 / 1"""
import http.client, http.server, json, os, pathlib, re, shlex, shutil, socket, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance

T = pathlib.Path(_scratch.mkdtemp(prefix="frontdoorunits-"))
fails = []; ran = []; skipped = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

toml = _instance.apply(_instance.base_toml())
toml, n = re.subn(r'(?m)^session_links = ".*"', 'session_links = ""', toml, count=1); assert n == 1   # session links off: no session store of the host is read
FRONT = ("stackshot-frontdoor.service", "stackshot-signin.service", "stackshot-splitter.service")
CADDYUNIT = "stackshot-splitter.Caddyfile"

# ---------------------------------------------------------------- stubs
(T / "bin").mkdir(); (T / "active").mkdir(); (T / "restart-fails").mkdir()
(T / "bin/sudo").write_text(f'#!/bin/sh\ntouch {T}/sudo-called\nexit 1\n')
(T / "bin/loginctl").write_text('#!/bin/sh\ncase "$*" in show-user*) echo yes ;; esac\nexit 0\n')
# is-active answers what the file active/<unit> holds (inactive without one); a unit named in restart-fails/ cannot be restarted
(T / "bin/systemctl").write_text(f'''#!/bin/sh
echo "$*" >> {T}/systemctl.log
u=""; for a; do u="$a"; done
case "$*" in
  *is-active*) if [ -f {T}/active/$u ]; then cat {T}/active/$u; exit 0; fi; echo inactive; exit 3 ;;
  *is-enabled*) exit 1 ;;
  *restart*) if [ -f {T}/restart-fails/$u ]; then echo "Job for $u failed." >&2; exit 1; fi ;;
esac
exit 0
''')
for n in ("sudo", "loginctl", "systemctl"): (T / "bin" / n).chmod(0o755)

def fake_caddy(name, line, status=0):
    p = T / name
    p.write_text(f'#!/bin/sh\n[ "$1" = version ] || exit 64\nprintf "%s\\n" {shlex.quote(line)}\nexit {status}\n'); p.chmod(0o755)
    return str(p)
CADDY = fake_caddy("caddy-new", "v2.11.6 h1:abcdef=")

ENV = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG")}
ENV.update({"PATH": f"{T}/bin:" + os.environ.get("PATH", ""), "STACKSHOT_SYSTEM_UNIT_DIR": str(T / "etc-systemd")})

# ---------------------------------------------------------------- configs
def conf(name, tables=(), server_port=18010, splitter_port=18020, door_port=18030, signin_port=18031, header="X-Forwarded-User", caddy=CADDY, path="/mcp", splitter_extra=""):
    """A config file: the example, the board on `server_port`, and the front door's tables named in `tables` (door, signin, splitter)."""
    t, n = re.subn(r'(?ms)^(\[server\]\n.*?^port = )\d+', lambda m: m.group(1) + str(server_port), toml, count=1); assert n == 1
    t, n = re.subn(r'(?ms)^(\[server\]\n.*?^path = )"/mcp"', lambda m: m.group(1) + f'"{path}"', t, count=1); assert n == 1
    assert not re.search(r"(?m)^\[+(frontdoor|behind_frontdoor)", t)
    if "door" in tables:
        t += (f'\n[frontdoor]\nlisten_port = {door_port}\nidentity_header = "{header}"\nidentity_secret_file = "{T}/identity.key"\nmembers_file = "{T}/members.json"\n'
              f'\n[[frontdoor.backends]]\nname = "main"\nurl = "http://127.0.0.1:{server_port}/mcp"\ntoken_file = "{T}/main.token"\n')
    if "signin" in tables:
        t += (f'\n[frontdoor_signin]\nlisten_port = {signin_port}\nboard_verify_url = "http://127.0.0.1:{server_port}/frontdoor/verify"\nverify_secret_file = "{T}/verify.key"\n')
    if "splitter" in tables:
        t += f'\n[frontdoor_splitter]\nlisten_port = {splitter_port}\ncaddy = "{caddy}"\n{splitter_extra}'
    p = T / name; p.write_text(t, encoding="utf-8"); return str(p)

ALL = ("door", "signin", "splitter")
def render(cfg, *names, home=None):
    r = subprocess.run([os.path.join(STACK, "install.sh"), "render", *names, "--config", cfg], capture_output=True, text=True, env={**ENV, "HOME": str(home or T / "rhome")}, timeout=120)
    return r.returncode, r.stdout, r.stderr
def headers(text): return re.findall(r"(?m)^# Rendered by install\.sh from units/(\S+)\.in", text)
def units(home, cfg, *extra):
    (T / "systemctl.log").unlink(missing_ok=True)
    r = subprocess.run([os.path.join(STACK, "install.sh"), "units", "--config", cfg, *extra], capture_output=True, text=True, env={**ENV, "HOME": str(home)}, stdin=subprocess.DEVNULL, timeout=180)
    calls = (T / "systemctl.log").read_text().splitlines() if (T / "systemctl.log").exists() else []
    return r.returncode, r.stdout + r.stderr, calls
def udir(home): return home / ".config/systemd/user"
def cfile(home): return home / ".config/stackshot/splitter.Caddyfile"
def front_calls(calls): return [c for c in calls if any(f in c for f in FRONT)]
def acting(calls): return [c for c in front_calls(calls) if re.search(r"\b(enable|start|restart|reload|try-restart|reload-or-restart)\b", c)]

# ---------------------------------------------------------------- 1. without the tables nothing changes
off = conf("off.toml")
rc, out, err = render(off)
check("no front door table: render lists no front door file", rc == 0 and not [h for h in headers(out) if "frontdoor" in h or "signin" in h or "splitter" in h], (headers(out), err[-300:]))
H0 = T / "home-off"
rc, out, calls = units(H0, off)
check("no front door table: units installs no front door file", rc == 0 and not [p for p in udir(H0).iterdir() if "frontdoor" in p.name or "signin" in p.name or "splitter" in p.name] and not cfile(H0).exists(),
      (rc, out[-600:]))
check("no front door table: the output and the systemctl calls do not mention the front door", not re.search(r"(?i)front ?door|frontdoor|signin|splitter|caddy", out.replace(str(T), "")) and not front_calls(calls), (out[-900:], front_calls(calls)))
check("no front door table: ~/.config/stackshot is not made by units", not (H0 / ".config/stackshot").exists(), list((H0 / ".config").iterdir()))

# ---------------------------------------------------------------- 2. all tables: rendered, installed, never enabled or started
on = conf("on.toml", ALL)
rc, out, err = render(on)
check("all tables: render ends with the front door's files, the Caddyfile among them", rc == 0 and headers(out)[-4:] == ["stackshot-frontdoor.service", "stackshot-signin.service", CADDYUNIT, "stackshot-splitter.service"],
      (rc, headers(out), err[-300:]))
H1 = T / "home-on"
rc, out, calls = units(H1, on)
check("all tables: units installs the three units and the Caddyfile", rc == 0 and all((udir(H1) / n).is_file() for n in FRONT) and cfile(H1).is_file(), (rc, out[-900:]))
check("all tables: a ~/.config/stackshot that units makes is private (mode 700)", (H1 / ".config/stackshot").stat().st_mode & 0o777 == 0o700, oct((H1 / ".config/stackshot").stat().st_mode & 0o777))
for n, p in (*((f, udir(H1) / f) for f in FRONT), (CADDYUNIT, cfile(H1))):
    rc_r, text, err = render(on, n, home=H1)
    check(f"all tables: {n} is installed as render prints it", rc_r == 0 and p.is_file() and p.read_text() == text, (rc_r, err[-300:], text[:300]))
check("all tables: no systemctl call names a front door unit at all", calls and front_calls(calls) == [], front_calls(calls))
check("all tables: units says that starting them is the person's step", "front door units: never enabled or started by this script" in out and "systemctl --user enable --now" in out, out[-600:])
rc, out, calls = units(H1, on)
check("all tables, twice: the front door's four files are unchanged", rc == 0 and all(f"{n}: unchanged" in out for n in (*FRONT, CADDYUNIT)), out[-900:])
rc, out, calls = units(H1, on, "--start")
check("--start with the units stopped: none is enabled, started or restarted", rc == 0 and acting(calls) == [], (rc, acting(calls), out[-400:]))
H2 = T / "home-start"
rc, out, calls = units(H2, on, "--start")
check("--start on a first install: none is enabled, started or restarted", rc == 0 and acting(calls) == [] and (udir(H2) / "stackshot-splitter.service").is_file(), (rc, acting(calls), out[-400:]))
rc, out, calls = units(T / "home-restart-first", on, "--restart")
check("--restart on a first install: none is enabled, started or restarted", rc == 0 and acting(calls) == [], (rc, acting(calls), out[-400:]))

def stale(*names):
    for n in names: (cfile(H1) if n == CADDYUNIT else udir(H1) / n).write_text("stale\n")
def running(**state):
    for p in (T / "active").iterdir(): p.unlink()
    for n, s in state.items(): (T / "active" / f"stackshot-{n}.service").write_text(s + "\n")
def restarted(calls): return [c.split()[-1] for c in calls if " restart " in f" {c} " and c.split()[-1] in FRONT]

for flag in ("--restart", "--start"):
    stale("stackshot-frontdoor.service", "stackshot-splitter.service", CADDYUNIT); running(frontdoor="active", signin="active", splitter="active")
    rc, out, calls = units(H1, on, flag)
    check(f"{flag}: a running unit whose file changed is restarted, once, and an unchanged one is not", rc == 0 and restarted(calls) == ["stackshot-frontdoor.service", "stackshot-splitter.service"]
          and not [c for c in front_calls(calls) if " enable " in f" {c} "], (rc, restarted(calls), out[-400:]))
    stale(CADDYUNIT); running(splitter="active")
    rc, out, calls = units(H1, on, flag)
    check(f"{flag}: a changed Caddyfile alone restarts the running splitter", rc == 0 and restarted(calls) == ["stackshot-splitter.service"], (rc, restarted(calls), out[-400:]))
    stale("stackshot-frontdoor.service", "stackshot-signin.service", CADDYUNIT); running(frontdoor="failed")
    rc, out, calls = units(H1, on, flag)
    check(f"{flag}: a changed unit that is stopped or failed is not started", rc == 0 and acting(calls) == [], (rc, acting(calls), out[-400:]))
stale("stackshot-signin.service"); running(signin="activating")
rc, out, calls = units(H1, on, "--restart")
check("--restart: a unit that is starting counts as running", rc == 0 and restarted(calls) == ["stackshot-signin.service"], (rc, restarted(calls)))
stale("stackshot-frontdoor.service"); running(frontdoor="active")
rc, out, calls = units(H1, on)
check("no flag: a changed running unit is installed and not restarted", rc == 0 and acting(calls) == [] and "stackshot-frontdoor.service: installed" in out, (rc, acting(calls), out[-400:]))
for flag in ("--restart", "--start"):
    stale("stackshot-frontdoor.service"); running(frontdoor="active"); (T / "restart-fails/stackshot-frontdoor.service").write_text("")
    rc, out, calls = units(H1, on, flag)
    check(f"{flag}: a front door unit that cannot be restarted fails the run, named", rc != 0 and "FAILED to restart stackshot-frontdoor.service" in out, (rc, out[-500:]))
    (T / "restart-fails/stackshot-frontdoor.service").unlink()
running()

# ---------------------------------------------------------------- 3. each table brings its own unit
for tables, want in ((("door",), ["stackshot-frontdoor.service"]), (("signin",), ["stackshot-signin.service"]), (("door", "signin"), ["stackshot-frontdoor.service", "stackshot-signin.service"])):
    c = conf("only-" + "-".join(tables) + ".toml", tables); h = T / ("home-" + "-".join(tables))
    rc, out, calls = units(h, c)
    have = sorted(p.name for p in udir(h).iterdir() if p.name in FRONT)
    check(f"tables {', '.join(tables)}: only {', '.join(want)}, and not a word about a splitter", rc == 0 and have == sorted(want) and not cfile(h).exists() and "splitter" not in out.replace(str(T), ""), (rc, have, out[-600:]))

# ---------------------------------------------------------------- 4. a splitter the config does not allow
BLOCKED = (
    ("the board's own port", conf("same.toml", ALL, server_port=18020), "listen_port 18020 is the port [server] port gives the board"),
    ("no sign-in table", conf("nosignin.toml", ("door", "splitter")), "no [frontdoor_signin] table"),
    ("no front door table", conf("nodoor.toml", ("signin", "splitter")), "no [frontdoor] table"),
    ("another MCP path", conf("path.toml", ALL, path="/board"), "[server] path is '/board'"),
    ("two services on one port", conf("ports.toml", ALL, signin_port=18030), "need four different ports"),
    ("an identity header nothing can send", conf("noheader.toml", ALL, header="Host"), "[frontdoor] names no usable identity_header"),
    ("no listen_port", conf("noport.toml", ("door", "signin"), ), None),
)
for label, c, why in BLOCKED:
    if why is None:
        pathlib.Path(c).write_text(pathlib.Path(c).read_text() + f'\n[frontdoor_splitter]\ncaddy = "{CADDY}"\n'); why = "no usable listen_port"
    h = T / ("home-blocked-" + re.sub(r"\W+", "-", label))
    rc, out, calls = units(h, c)
    check(f"splitter with {label}: not installed, and the reason is said", rc == 0 and not (udir(h) / "stackshot-splitter.service").exists() and not cfile(h).exists()
          and "stackshot-splitter.service: skipped (" in out and why in out and acting(calls) == [], (rc, out[-700:]))
    for n in ("stackshot-splitter.service", CADDYUNIT):
        rc, text, err = render(c, n)
        check(f"splitter with {label}: render of {n} by name is refused with the reason", rc != 0 and f"{n}: not rendered: " in err and why in err and "[Service]" not in text, (rc, err[-400:], text[:200]))

# an undo: the config gives the port back after the splitter was installed
H3 = T / "home-undo"
rc, out, calls = units(H3, on)
before = ((udir(H3) / "stackshot-splitter.service").read_text(), cfile(H3).read_text())
undone = conf("undone.toml", ALL, server_port=18020)
running(splitter="active")
rc, out, calls = units(H3, undone, "--restart")
check("undo: the installed splitter files stay as they were, the run says so and that its own check refuses a start, and it is not restarted",
      rc == 0 and ((udir(H3) / "stackshot-splitter.service").read_text(), cfile(H3).read_text()) == before and "the installed unit stays as it is, and its own check refuses to start it" in out
      and "stackshot-splitter.service" not in " ".join(acting(calls)), (rc, out[-700:], acting(calls)))
running()
rc, out, calls = units(H3, off)
check("tables gone: each installed front door unit is said to stay", rc == 0 and all(f"{n}: skipped (the config has no [" in out for n in FRONT) and all((udir(H3) / n).is_file() for n in FRONT), (rc, out[-900:]))

# ---------------------------------------------------------------- 5. the unit files
def lines(p, key): return [l[len(key) + 1:] for l in p.read_text().splitlines() if l.startswith(key + "=")]
real_on = os.path.realpath(on)
for n, module in (("stackshot-frontdoor.service", "stackshot.frontdoor"), ("stackshot-signin.service", "stackshot.frontdoor.signin")):
    p = udir(H1) / n; rc, text, _ = render(on, n, home=H1); p.write_text(text)
    check(f"{n}: restarted and stopped with the board, and started with it once enabled", lines(p, "PartOf") == ["stackshot.service"] and lines(p, "WantedBy") == ["default.target stackshot.service"], (lines(p, "PartOf"), lines(p, "WantedBy")))
    ex = lines(p, "ExecStart")
    check(f"{n}: runs the module in the checkout's locked environment with the server extra", len(ex) == 1 and re.fullmatch(r"\S+ run --project " + re.escape(STACK) + r" --locked --extra server python -m " + re.escape(module), ex[0])
          and lines(p, "Environment")[0] == f"STACKSHOT_CONFIG={real_on}", (ex, lines(p, "Environment")))
    check(f"{n}: settings that allow no start end the unit and no restart loop", lines(p, "Restart") == ["on-failure"] and lines(p, "RestartPreventExitStatus") == ["2"], p.read_text())
sp_unit = udir(H1) / "stackshot-splitter.service"; rc, text, _ = render(on, "stackshot-splitter.service", home=H1); sp_unit.write_text(text)
check("splitter unit: not part of the board's restarts, wanted by default.target only", lines(sp_unit, "PartOf") == [] and lines(sp_unit, "WantedBy") == ["default.target"], sp_unit.read_text())
check("splitter unit: the check runs before every start, with the values it was rendered with", lines(sp_unit, "ExecStartPre") ==
      [f"/usr/bin/python3 -m stackshot.frontdoor.splitter check --listen 18020 --board 127.0.0.1:18010 --door 127.0.0.1:18030 --signin 127.0.0.1:18031 --header x-forwarded-user --caddy {CADDY}"]
      and lines(sp_unit, "WorkingDirectory") == [STACK] and lines(sp_unit, "Environment") == [f"STACKSHOT_CONFIG={real_on}"], sp_unit.read_text())
check("splitter unit: runs the configured Caddy with the rendered Caddyfile", lines(sp_unit, "ExecStart") == [f'{CADDY} run --config "{cfile(H1)}" --adapter caddyfile'] and lines(sp_unit, "Type") == ["notify"], lines(sp_unit, "ExecStart"))
rc, ctext, _ = render(on, CADDYUNIT, home=H1)
code = [l.strip() for l in ctext.splitlines() if l.strip() and not l.strip().startswith("#")]
for want in ("admin off", "auto_https off", "persist_config off", "bind 127.0.0.1", "http://:18020 {", "trusted_proxies static 127.0.0.1/32 ::1/128", "request_header -x-forwarded-user", "request_header -X-Forwarded-User", "request_header -X-Verified-User",
             "request_header -X-Stackshot-Identity", "request_header -X-Stackshot-Verify", "@token_check path /frontdoor /frontdoor/*", "respond @token_check 404", "@mcp path /mcp /mcp/*",
             "forward_auth @mcp 127.0.0.1:18031 {", "uri /verify", "copy_headers X-Verified-User>x-forwarded-user", "reverse_proxy @mcp 127.0.0.1:18030", "reverse_proxy 127.0.0.1:18010"):
    check(f"Caddyfile: has the line `{want}`", want in code, code)
check("Caddyfile: no placeholder is left, and the identity headers are removed before the check", not re.search(r"@[A-Z0-9_]+@", "\n".join(code))
      and code.index("request_header -x-forwarded-user") < code.index("forward_auth @mcp 127.0.0.1:18031 {") and code.index("respond @token_check 404") < code.index("reverse_proxy 127.0.0.1:18010"), code)
named = re.search(r'(?m)^VERIFY_HEADER = "([a-z0-9-]+)"', pathlib.Path(STACK, "stackshot/core/behind_door.py").read_text(encoding="utf-8"))      # a rename there has to reach the Caddyfile
check("Caddyfile: removes the header the board's token check is signed with, by the board's own name for it",
      named is not None and f"request_header -{named.group(1)}" in [l.lower() for l in code], named and named.group(1))
other = conf("other-header.toml", ALL, header="X-Auth-Email")
rc, ctext2, _ = render(other, CADDYUNIT)
check("Caddyfile: the configured identity header is removed from clients and is what the check's answer is copied into", "request_header -x-auth-email" in ctext2 and "copy_headers X-Verified-User>x-auth-email" in ctext2, ctext2)

# ---------------------------------------------------------------- 6. the check before every start
pre = shlex.split(lines(sp_unit, "ExecStartPre")[0])
def start_check(cfg, argv=None):
    """The unit's own ExecStartPre line, run as systemd runs it: the system's python3, in the checkout, with the unit's environment and nothing of this process's Python."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(T / "rhome"), "STACKSHOT_CONFIG": cfg}
    return subprocess.run(argv or pre, cwd=STACK, env=env, capture_output=True, text=True, timeout=60)
r = start_check(on)
check("start check: the rendered line passes with the config it was rendered from", r.returncode == 0 and "allows it to listen on port 18020" in r.stdout, (r.returncode, r.stdout, r.stderr[-600:]))
def refused(name, cfg, why, argv=None):
    r = start_check(cfg, argv)
    check(f"start check: refuses {name}", r.returncode == 1 and r.stderr.startswith("splitter: not started: ") and why in r.stderr and r.stderr.count("\n") == 1, (r.returncode, r.stdout, r.stderr[-600:]))
refused("a start after the config gave the port back to the board (an undo, then a reboot)", undone, "is the port [server] port gives the board")
refused("a config whose splitter table is gone", conf("nosplit.toml", ("door", "signin")), "no [frontdoor_splitter] table")
refused("a config with no front door table left", off, "no [frontdoor_splitter] table")
refused("a board moved to another port than the unit was rendered with", conf("moved.toml", ALL, server_port=18011), "the installed unit is older than the config (board_addr was '127.0.0.1:18010' and is '127.0.0.1:18011' now)")
refused("a changed identity header", other, "the installed unit is older than the config (identity_header")
refused("a changed front door port", conf("doormoved.toml", ALL, door_port=18040), "older than the config (door_addr")
refused("a changed sign-in port", conf("signmoved.toml", ALL, signin_port=18041), "older than the config (signin_addr")
refused("a changed splitter port", conf("splitmoved.toml", ALL, splitter_port=18042), "older than the config (listen_port")
def with_caddy(path):
    cfg = conf("caddy-" + pathlib.Path(path).name + ".toml", ALL, caddy=path)
    return cfg, [*pre[:-1], path]
for name, line, status, ok, why in (
        ("caddy-old", "v2.11.4 h1:x=", 0, False, "is Caddy v2.11.4: the splitter needs 2.11.6 or later"),
        ("caddy-older", "v2.9.9", 0, False, "needs 2.11.6 or later"),
        ("caddy-beta", "v2.11.6-beta.1 h1:x=", 0, False, "is Caddy v2.11.6-beta.1: the splitter needs 2.11.6 or later"),
        ("caddy-next-patch", "v2.11.7 h1:x=", 0, True, ""),
        ("caddy-minor", "v2.12.0-beta.1 h1:x=", 0, True, ""),
        ("caddy-ten", "v2.100.0", 0, True, ""),
        ("caddy-major", "v3.0.0", 0, True, ""),
        ("caddy-no-v", "2.11.6", 0, True, ""),
        ("caddy-words", "unknown", 0, False, "gave no version that can be read (exit 0)"),
        ("caddy-silent", "", 0, False, "gave no version that can be read"),
        ("caddy-broken", "v2.11.6 h1:x=", 1, False, "gave no version that can be read (exit 1)")):
    cfg, argv = with_caddy(fake_caddy(name, line, status))
    if ok:
        r = start_check(cfg, argv)
        check(f"start check: passes with Caddy answering {line!r}", r.returncode == 0, (r.returncode, r.stderr[-400:]))
    else:
        refused(f"Caddy answering {line!r} (exit {status})", cfg, why, argv)
cfg, argv = with_caddy(str(T / "caddy-absent"))
refused("a Caddy that is not there", cfg, "could not be run (FileNotFoundError)", argv)
(T / "caddy-noexec").write_text("#!/bin/sh\necho v2.11.6\n")
cfg, argv = with_caddy(str(T / "caddy-noexec"))
refused("a Caddy that cannot be executed", cfg, "could not be run (PermissionError)", argv)

# ---------------------------------------------------------------- 7. the rendered Caddyfile in a real Caddy
def free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    for s in socks: s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks: s.close()
    return ports

class StandIn:
    """One of the services behind the splitter: records each request; the sign-in stand-in answers 200 with an identity for the bearer `good`, else 401."""
    def __init__(self, name, port):
        self.seen = seen = []
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_any(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                seen.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}))
                code, extra = 200, {}
                if name == "signin":
                    if self.headers.get("Authorization") == "Bearer good": extra = {"X-Verified-User": "person@example.com"}
                    else: code = 401
                body = name.encode()
                self.send_response(code)
                for k, v in extra.items(): self.send_header(k, v)
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            do_GET = do_POST = do_DELETE = do_any
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def stop(self): self.srv.shutdown(); self.srv.server_close()

def listening(port):
    """The local addresses (hex, as /proc/net/tcp writes them) that listen on `port`."""
    out = []
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        try: rows = pathlib.Path(f).read_text().splitlines()[1:]
        except OSError: continue
        for row in rows:
            local, state = row.split()[1], row.split()[3]
            addr, p = local.split(":")
            if state == "0A" and int(p, 16) == port: out.append(addr)
    return out

def real_caddy(caddy):
    bport, dport, sport, lport = free_ports(4)
    cfg = conf("real.toml", ALL, server_port=bport, door_port=dport, signin_port=sport, splitter_port=lport, caddy=caddy, header="X-Auth-Email")
    home = T / "home-real"
    rc, out, calls = units(home, cfg)
    check("real Caddy: the splitter is installed", rc == 0 and cfile(home).is_file(), out[-500:])
    root = T / "caddy-run"; root.mkdir()
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data")}
    v = subprocess.run([caddy, "validate", "--config", str(cfile(home)), "--adapter", "caddyfile"], env=env, capture_output=True, text=True, timeout=60)
    check("real Caddy: validates the rendered Caddyfile", v.returncode == 0, v.stderr[-900:])
    r = subprocess.run(shlex.split(lines(udir(home) / "stackshot-splitter.service", "ExecStartPre")[0]), cwd=STACK, env={**env, "STACKSHOT_CONFIG": cfg}, capture_output=True, text=True, timeout=60)
    check("real Caddy: the unit's start check passes with it", r.returncode == 0, r.stderr[-400:])
    stands = {n: StandIn(n, p) for n, p in (("board", bport), ("door", dport), ("signin", sport))}
    log = open(root / "caddy.log", "wb")
    proc = subprocess.Popen([caddy, "run", "--config", str(cfile(home)), "--adapter", "caddyfile"], env=env, cwd=str(root), stdout=log, stderr=subprocess.STDOUT)
    try:
        end = time.monotonic() + 30
        while time.monotonic() < end and proc.poll() is None and not listening(lport): time.sleep(0.05)
        check("real Caddy: runs and listens", proc.poll() is None and bool(listening(lport)), (root / "caddy.log").read_text()[-900:])
        check("real Caddy: listens on the loopback address only", listening(lport) == ["0100007F"], listening(lport))
        check("real Caddy: no admin API is listening", not listening(2019) or "admin endpoint disabled" in (root / "caddy.log").read_text(), (root / "caddy.log").read_text()[-600:])
        def ask(path, method="GET", **hdr):
            for s in stands.values(): s.seen.clear()
            c = http.client.HTTPConnection("127.0.0.1", lport, timeout=20)
            try:
                c.request(method, path, body=b"{}" if method == "POST" else None, headers={k.replace("_", "-"): v for k, v in hdr.items()})
                r = c.getresponse(); return r.status, r.read().decode(), {n: list(s.seen) for n, s in stands.items()}
            finally:
                c.close()
        forged = {"X_Auth_Email": "forged@example.com", "X_Forwarded_User": "forged@example.com", "X_Verified_User": "forged@example.com", "X_Stackshot_Identity": "forged", "X_Stackshot_Verify": "forged"}
        gone = lambda h, keep=(): not [k for k in ("x-auth-email", "x-forwarded-user", "x-verified-user", "x-stackshot-identity", "x-stackshot-verify") if k in h and k not in keep]
        code_, body, seen = ask("/healthz", **forged)
        check("real Caddy: another path goes to the board only, without the client's identity headers", code_ == 200 and body == "board" and len(seen["board"]) == 1 and not seen["door"] and not seen["signin"]
              and gone(seen["board"][0][2]), (code_, body, seen))
        for path in ("/frontdoor/verify", "/frontdoor", "/frontdoor/other", "//frontdoor/verify", "/%66rontdoor/verify"):
            code_, body, seen = ask(path, **forged)
            check(f"real Caddy: {path} is refused with 404 and reaches nothing", code_ == 404 and not any(seen.values()), (code_, body, seen))
        code_, body, seen = ask("/mcp", "POST", **forged)
        check("real Caddy: a call with no good token is the check's 401, the door and the board unasked", code_ == 401 and len(seen["signin"]) == 1 and not seen["door"] and not seen["board"]
              and seen["signin"][0][1] == "/verify" and gone(seen["signin"][0][2]), (code_, seen))
        code_, body, seen = ask("/mcp", "POST", Authorization="Bearer good", **forged)
        check("real Caddy: a checked call goes to the front door with the check's identity in the configured header, never the client's",
              code_ == 200 and body == "door" and len(seen["door"]) == 1 and not seen["board"] and seen["door"][0][2].get("x-auth-email") == "person@example.com" and gone(seen["door"][0][2], keep=("x-auth-email",)), (code_, body, seen))
        code_, body, seen = ask("/mcp/", "POST", Authorization="Bearer good")
        check("real Caddy: the MCP path with a slash is checked too", code_ == 200 and body == "door" and len(seen["signin"]) == 1 and not seen["board"], (code_, body, seen))
        for path in ("//mcp", "/%6dcp", "/MCP"):
            code_, body, seen = ask(path, "POST")
            check(f"real Caddy: {path} does not reach the board's MCP path unchecked", not [s for s in seen["board"] if s[1].lower().replace("//", "/").rstrip("/") == "/mcp" or "%6d" in s[1].lower()], (code_, body, seen))
    finally:
        proc.terminate()
        try: proc.wait(20)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(20)
        log.close()
        for s in stands.values(): s.stop()

if shutil.which("caddy"):
    print("note: " + subprocess.run(["caddy", "version"], capture_output=True, text=True, timeout=60).stdout.strip(), flush=True)
    real_caddy(shutil.which("caddy"))
else:
    skipped.append("the real Caddy checks (no caddy on this machine's PATH)")

check("end: sudo was never called", not (T / "sudo-called").exists())
for s in skipped: print(f"skipped: {s}", flush=True)
print(("ok" if not fails else "FAILED") + f": front door units scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "") + (f", {len(skipped)} part skipped" if skipped else ""), flush=True)
sys.exit(1 if fails else 0)
