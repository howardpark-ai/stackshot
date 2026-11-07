"""Scenario test for the Machines panel's machine cards — fixture data, a fake ssh, no live store, no network, no server.

Covers: one card per machine with its name as the bold first label (box-a, box-c, box-b, box-e from the fleet, then box-d and
box-g from [machines_panel] ssh_hosts, in config order), the package rows inside it with their state words (latest ✓, update <version>,
offline); an alert card (a failed setup step) under its machine's card, outside it; an ssh host read with ONE ssh call per host that asks every
package, a package the host lacks giving no row, a version behind the latest showing "update"; the read cached between writes, read again on
force; an unreachable host showing offline with its last versions and, if it never answered, one offline row; the script that goes over ssh
(each command in its own subshell, the executable's directory on PATH, a missing executable silent) run for real here under bash; and the
default (no ssh_hosts) changing nothing and never calling ssh; and a host that is also a fleet machine drawn as that machine's one card (ssh-probed versions, the fleet's rows, its alert card).

    tests/run-suite machines        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging, subprocess, datetime, shutil
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="machinestest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^latest_lookups = true', 'latest_lookups = false', toml); assert n == 1                  # never npm or GitHub
toml, n = re.subn(r'(?m)^ssh_hosts = \[\]', 'ssh_hosts = ["box-d", "box-g"]', toml); assert n == 1
toml += '\n[[machines_panel.packages]]\nname = "gbrain"\nowner = ""\ninstalled = "cmd:~/.bun/bin/gbrain --version"\nmachines = ["a"]\nlatest = "github-release:x/y"\n'
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "fleet/b", "fleet/d", "fleet/x", "state/site", "state/anchor-hub", "secrets", "touch"): (T / d).mkdir(parents=True)
for L, nm, cv in (("a", "box-a", "1.7.40"), ("b", "box-c", "1.7.30"), ("d", "box-b", "1.7.40"), ("x", "box-e", "1.7.40")):
    m = {"letter": L, "fleet": nm, "claude": cv}
    if L != "a": m["online"] = {"ok": L != "x", "since": "2026-10-20T00:00:00Z"}       # x: a puller that stopped checking in
    (T / f"fleet/{L}/machine.json").write_text(json.dumps(m)); (T / f"fleet/{L}/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "state/site/versions.latest.json").write_text(json.dumps({"claude code": "1.7.40", "gbrain": "1.9.12"}))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"))
    if not cond: fails.append(name)

import versions as ver
from ui import render as ui_render
ver._installed_cmd = lambda cmd: "1.9.12" if "gbrain" in cmd else "1.7.40"      # this box's own copies, not run here

CALLS = []                                                       # every ssh call: (host, script)
ANSWER = {                                                        # host → (exit code, {package index asked → what it prints}); a missing key = the command printed nothing
    "box-d": (0, {"claude code": "1.7.39 (Claude Code)", "gbrain": "gbrain 1.9.12"}),
    "box-g": (0, {"gbrain": "gbrain 1.9.10"}),         # no claude there
}
PKGS = [pk["name"] for pk in ver._cfg.get("machines_panel", "packages")]
def fake_ssh(host, script, timeout=10):
    CALLS.append((host, script))
    rc, said = ANSWER[host]
    if rc != 0: return rc, ""
    asked = [int(x) for x in re.findall(r"@@(\d+)", script)]
    return 0, "".join(f"@@{i}\n{said.get(PKGS[i], '')}\n" for i in asked)
ver._ssh = fake_ssh

def panel():
    h = ui_render.Board(str(T / "store")).render({"html"})["html"]
    sec = h[h.find('<section id="machines">'):]; return sec[:sec.find("</details>")]      # the fold's body: the drag grip after it carries a title of its own
def ncards(sec): return len(re.findall(r'<div class="pc mach[" ]', sec))      # a card with a failure line carries the alert border: "pc mach bad"
def names(sec): return re.findall(r'<b class="lbl mh">([^<]*)</b>', sec)
def card(sec, name):
    cols = sec.split('<div class="mcol">')[1:]
    return next((c for c in cols if f'">{name}</b>' in c.split("</b>")[0] + "</b>"), "")
def rows(c):
    return re.findall(r'<div class="mr (\w+)"><(?:span|a)[^>]*>([^<]*)</(?:span|a)><span class="val">([^<]*)</span><span class="st[^"]*">([^<]*)</span></div>', c)

# ---- the ssh script
bindir = T / "bin"; bindir.mkdir()
(bindir / "tool-a").write_text('#!/bin/sh\necho "tool-a 1.2.3 (build x)"\n'); (bindir / "tool-b").write_text('#!/usr/bin/env helper\n')
(bindir / "helper").write_text('#!/bin/sh\necho "b-version 4.5.6"\n')
for f in ("tool-a", "tool-b", "helper"): (bindir / f).chmod(0o755)
script = ver._ssh_script([(0, f"{bindir}/tool-a --version"), (1, f"{bindir}/tool-b"), (2, f"{bindir}/missing --version")])
r = subprocess.run(["bash", "-c", ver._remote(script)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})       # as ssh hands it to the login shell (sh -c '<script>'), with a PATH that has no `helper`
got = ver._ssh_parse(r.stdout, {0: "a", 1: "b", 2: "c"})
check("ssh script: every package in one script, each its version token, a #!/usr/bin/env script finding its runtime next to it, a missing executable silent",
      r.returncode == 0 and got == {"a": "1.2.3", "b": "4.5.6"}, (r.returncode, r.stdout, r.stderr, got))
check("ssh script: a command's own `~` is left for the remote shell to expand", "p=~/.bun/bin/gbrain" in ver._ssh_script([(0, "~/.bun/bin/gbrain --version")]) and "/home/" not in ver._ssh_script([(0, "~/.bun/bin/gbrain --version")]))
check("ssh command: ssh_cmd, else the cmd: command, else self_cmd",
      ver._ssh_cmd({"ssh_cmd": "x --v", "installed": "cmd:y"}) == "x --v" and ver._ssh_cmd({"installed": "cmd:y --version"}) == "y --version"
      and ver._ssh_cmd({"installed": "fleet", "self_cmd": "z --version"}) == "z --version" and ver._ssh_cmd({"installed": "fleet"}) == "")

# ---- the first read: six cards
doc = ver.write(force=True)
check("ssh read: one ssh call per host, both packages asked in it", [h for h, _ in CALLS] == ["box-d", "box-g"]
      and all(s.count("@@") == 2 for _, s in CALLS), CALLS)
hs = {h["name"]: h for h in doc.get("ssh_hosts", [])}
check("ssh read: versions.json lists the hosts in config order with their versions; a package a host lacks is not listed",
      [h["name"] for h in doc["ssh_hosts"]] == ["box-d", "box-g"] and hs["box-d"]["reachable"] is True
      and hs["box-d"]["packages"] == {"claude code": "1.7.39", "gbrain": "1.9.12"} and hs["box-g"]["packages"] == {"gbrain": "1.9.10"}
      and "ts" not in hs["box-d"] and hs["box-d"]["checked"], doc.get("ssh_hosts"))
sec = panel()
check("six cards, the machine's name the bold first label inside each: the fleet's, then the ssh hosts in config order",
      names(sec) == ["box-a", "box-c", "box-b", "box-e", "box-d", "box-g"] and ncards(sec) == 6, names(sec))
check("a card is its name, then its rows: no heading outside it", '<div class="mh"' not in sec and re.search(r'<div class="mcol"><div class="pc mach"><b class="lbl mh">box-a</b>', sec) is not None, sec[:600])
a, b, x, e, g = (card(sec, n) for n in ("box-a", "box-c", "box-e", "box-d", "box-g"))
check("fleet card: box-a has claude code and gbrain, both latest ✓",
      [(r[0], r[1], r[2], r[3]) for r in rows(a)] == [("latest", "claude code", "1.7.40", "latest ✓"), ("latest", "gbrain", "1.9.12", "latest ✓")], rows(a))
check("fleet card: a machine behind shows → <latest> (no word update); one whose puller stopped shows offline",
      [(r[0], r[3]) for r in rows(b)] == [("update", "→ 1.7.40")] and [(r[0], r[3]) for r in rows(x)] == [("offline", "offline")], (rows(b), rows(x)))
check("ssh card: box-d: claude 1.7.39 is behind the latest, shown → 1.7.40; gbrain 1.9.12 → latest ✓",
      [(r[0], r[1], r[2], r[3]) for r in rows(e)] == [("update", "claude code", "1.7.39", "→ 1.7.40"), ("latest", "gbrain", "1.9.12", "latest ✓")], rows(e))
check("ssh card: box-g has gbrain only (no claude row), 1.9.10 behind 1.9.12 → shown → 1.9.12",
      [(r[0], r[1], r[2], r[3]) for r in rows(g)] == [("update", "gbrain", "1.9.10", "→ 1.9.12")] and "claude code" not in g, rows(g))
check("update word: '→ <latest>', and no arrow at all while the latest version is empty, unknown or blank",
      ui_render._update_word("1.7.40") == "→ 1.7.40" and all(ui_render._update_word(x) == "" for x in ("", None, "?", "  ")), [ui_render._update_word(x) for x in ("1.7.40", "", None, "?")])
check("machine cards carry no hover text: no title attribute on any card, name or row, fleet or ssh host",
      ncards(sec) == 6 and all("title=" not in c for c in sec.split('<div class="mcol">')[1:]), sec[:600])
check("ssh card: a package the host lacks has no row: box-g's card has no claude code anywhere, box-d's has both",
      "claude code" not in g and "claude code" in e and len(rows(g)) == 1 and len(rows(e)) == 2, (g, e))

# ---- cache
CALLS.clear(); ver.write(force=False); ver.write(force=False)
check("cache: a write that is not forced reads the cache — no ssh call", CALLS == [], CALLS)
ver.write(force=True)
check("cache: a forced write reads each host once more", [h for h, _ in CALLS] == ["box-d", "box-g"], CALLS)
CALLS.clear(); old = json.loads(ver.SSH_OUT.read_text()); old["box-g"]["ts"] -= (ver.SSH_CACHE_MIN + 1) * 60; ver.SSH_OUT.write_text(json.dumps(old)); ver.write(force=False)
check("cache: an entry older than SSH_CACHE_MIN is read again, only that host", [h for h, _ in CALLS] == ["box-g"], CALLS)

# ---- an alert card stays outside the machine's card
m = json.loads((T / "fleet/b/machine.json").read_text())
m["setup"] = {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "winget exited"}; (T / "fleet/b/machine.json").write_text(json.dumps(m))
sec = panel(); b = card(sec, "box-c")
check("alert: a failed setup step is a failure line at the foot of the machine's card (the alert border, the reason in its hover text), not a version row",
      ncards(sec) == 6 and b.startswith('<div class="pc mach bad">') and b.count('<div class="mf"') == 1 and b.index('<div class="mf"') > b.rindex('<div class="mr ') and "setup failed ✗" in b and "Install Claude Code" in b
      and 'title="setup failed at step Install Claude Code' in b and "winget exited" in b and len(rows(b)) == 1, b)

# ---- an unreachable host
ANSWER["box-g"] = (255, {}); ANSWER["box-d"] = (255, {}); CALLS.clear()
doc = ver.write(force=True); hs = {h["name"]: h for h in doc["ssh_hosts"]}
check("unreachable: the host is marked so, keeps the versions it last had and when it last answered",
      hs["box-g"]["reachable"] is False and hs["box-g"]["packages"] == {"gbrain": "1.9.10"} and hs["box-g"].get("last_ok") and hs["box-d"]["packages"]["claude code"] == "1.7.39", hs)
sec = panel(); g = card(sec, "box-g"); e = card(sec, "box-d")
check("unreachable: its card shows offline on every row, its last versions kept, no hover text",
      [(r[0], r[2], r[3]) for r in rows(g)] == [("offline", "1.9.10", "offline")] and "title=" not in g and "last answered" not in g
      and [r[0] for r in rows(e)] == ["offline", "offline"] and ncards(sec) == 6, (g, rows(g)))
ver.SSH_OUT.unlink(); ver.write(force=True); g = card(panel(), "box-g")
check("unreachable: a host that never answered shows its card with one offline row and no hover text",
      '<div class="mr offline"><span class="st">offline</span></div>' in g and "title=" not in g, g)
ANSWER["box-g"] = (0, {"gbrain": "gbrain 1.9.12"}); ANSWER["box-d"] = (0, {}); ver.write(force=True)
sec = panel(); g = card(sec, "box-g"); e = card(sec, "box-d")
check("back online: the card is current again; a host that answers with no package at all shows a name and no rows",
      [(r[0], r[3]) for r in rows(g)] == [("latest", "latest ✓")] and rows(e) == [] and "offline" not in e, (g, e))

# ---- a host that is also a fleet machine is one card (box-d joined the fleet while the config still lists it in ssh_hosts)
(T / "fleet/e").mkdir(); (T / "fleet/e/sessions.json").write_text("{}")
(T / "fleet/e/machine.json").write_text(json.dumps({"letter": "e", "fleet": "box-d", "claude": "1.7.25", "online": {"ok": True, "since": "2026-10-20T00:00:00Z"}}))
ANSWER["box-d"] = (0, {"gbrain": "gbrain 1.9.12"}); ver.write(force=True); sec = panel(); e = card(sec, "box-d")
check("one card per machine: box-d, a fleet machine and an ssh host, is one card, in the fleet's place (after box-b, before box-e); the ssh-only host stays last",
      names(sec) == ["box-a", "box-c", "box-b", "box-d", "box-e", "box-g"] and ncards(sec) == 6, names(sec))
check("merged card: the fleet's row for a package the host did not answer (claude code 1.7.25, behind) and the ssh-probed gbrain, in the config's order",
      [(r[0], r[1], r[2], r[3]) for r in rows(e)] == [("update", "claude code", "1.7.25", "→ 1.7.40"), ("latest", "gbrain", "1.9.12", "latest ✓")], rows(e))
ANSWER["box-d"] = (0, {"claude code": "1.7.39 (Claude Code)", "gbrain": "gbrain 1.9.12"}); ver.write(force=True); e = card(panel(), "box-d")
check("merged card: a package both know shows the ssh-probed version once (1.7.39, not the fleet's 1.7.25), no row twice",
      [(r[1], r[2]) for r in rows(e)] == [("claude code", "1.7.39"), ("gbrain", "1.9.12")], rows(e))
m = json.loads((T / "fleet/e/machine.json").read_text()); m["setup"] = {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "winget exited"}; (T / "fleet/e/machine.json").write_text(json.dumps(m))
sec = panel(); e = card(sec, "box-d")
check("merged card: the fleet machine's failure line sits once at the foot of the one card, under its rows", e.count('<div class="mf"') == 1 and e.index('<div class="mf"') > e.rindex('<div class="mr ') and "Install Claude Code" in e and len(rows(e)) == 2 and ncards(sec) == 6, e)
ANSWER["box-d"] = (255, {}); ver.write(force=True); e = card(panel(), "box-d")
check("merged card: an unreachable host does not hide the live fleet's row: claude code stays the fleet's 1.7.25 (update, not offline); gbrain, which only the host ever had, shows its last version offline; once each",
      [(r[0], r[1], r[2]) for r in rows(e)] == [("update", "claude code", "1.7.25"), ("offline", "gbrain", "1.9.12")], rows(e))
ver.SSH_OUT.unlink(); ver.write(force=True); e = card(panel(), "box-d")
check("merged card: a host that never answered, with the fleet's row live, shows the fleet's row and no lone offline row", [(r[0], r[1]) for r in rows(e)] == [("update", "claude code")] and "offline" not in e, e)
ANSWER["box-d"] = (0, {}); ver.write(force=True); e = card(panel(), "box-d")
check("merged card: a host that answered with no package leaves the fleet's own row, with no offline row", [(r[0], r[1]) for r in rows(e)] == [("update", "claude code")], rows(e))
sec = panel()
check("one card per machine: the name appears once in the whole panel", names(sec).count("box-d") == 1 and sec.count(">box-d</b>") == 1, names(sec))
shutil.rmtree(T / "fleet/e")                                         # box-d is an ssh-only host again for the sections below

# ---- the default: no ssh_hosts
ver._cfg.CFG["machines_panel"]["ssh_hosts"] = []; CALLS.clear(); ver.SSH_OUT.unlink()
doc = ver.write(force=True); sec = panel()
check("default: no ssh_hosts → no ssh call, no key in versions.json, four cards",
      CALLS == [] and "ssh_hosts" not in doc and names(sec) == ["box-a", "box-c", "box-b", "box-e"], (CALLS, names(sec)))

# ---- config shapes, and a probe that fails
ANSWER["box-d"] = (0, {"gbrain": "gbrain 1.9.12"}); ANSWER["box-g"] = (0, {"gbrain": "gbrain 1.9.10"})
ver._cfg.CFG["machines_panel"]["ssh_hosts"] = "box-d"; CALLS.clear(); ver.SSH_OUT.unlink(missing_ok=True)
doc = ver.write(force=True)
check("config: ssh_hosts written as one string is a one-item list", [h for h, _ in CALLS] == ["box-d"] and [h["name"] for h in doc["ssh_hosts"]] == ["box-d"], (CALLS, doc.get("ssh_hosts")))
ver._cfg.CFG["machines_panel"]["ssh_hosts"] = ["-oProxyCommand=x", "bad host", "", "box-d", "box-d", "box-g"]; CALLS.clear()
doc = ver.write(force=True)
check("config: a host that starts with '-', holds whitespace or is empty is ignored, a repeat once; no ssh call for them",
      [h for h, _ in CALLS] == ["box-d", "box-g"] and [h["name"] for h in doc["ssh_hosts"]] == ["box-d", "box-g"], (CALLS, doc.get("ssh_hosts")))
good = fake_ssh
def flaky(host, script, timeout=10):
    if host == "box-g": raise RuntimeError("probe blew up")
    return good(host, script, timeout)
ver._ssh = flaky
c = json.loads(ver.SSH_OUT.read_text()); c["box-d"] = ["a damaged entry"]; ver.SSH_OUT.write_text(json.dumps(c))     # one damaged cache entry, one host whose probe raises
doc = ver.write(force=True); hs = {h["name"]: h for h in doc["ssh_hosts"]}; sec = panel()
check("a probe that raises or a damaged cache entry keeps that host's last state (offline) and drops no card",
      hs["box-g"]["reachable"] is False and hs["box-g"]["packages"] == {"gbrain": "1.9.10"} and hs["box-d"]["reachable"] is True
      and names(sec)[-2:] == ["box-d", "box-g"] and [r[0] for r in rows(card(sec, "box-g"))] == ["offline"], (hs, names(sec)))
ver._ssh = good

# ---- the real _ssh, its command line (subprocess.run replaced: nothing connects)
real = {}
def fake_run(cmd, **kw): real["cmd"] = cmd; real["kw"] = kw; return subprocess.CompletedProcess(cmd, 0, "@@0\nx 1.0.0\n", "")
import importlib; ver2 = importlib.reload(ver); ver2.subprocess.run = fake_run
rc, out = ver2._ssh("box-d", "echo hi")
check("ssh: key auth only, no shared connection, a dead link noticed, `--` before the host, the script as sh -c '<script>', a hard timeout, no stdin",
      real["cmd"] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=no", "-o", "ControlPath=none",
                      "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2", "--", "box-d", "sh -c 'echo hi'"] and real["kw"]["timeout"] == 10 and real["kw"]["stdin"] == subprocess.DEVNULL and rc == 0, real)
def boom(cmd, **kw): raise subprocess.TimeoutExpired(cmd, 10)
ver2.subprocess.run = boom
check("ssh: a timeout is an unreachable host (255), not an exception", ver2._ssh("box-d", "x") == (255, ""))

print(f"\n{len(ran) - len(fails)}/{len(ran)} passed")
sys.exit(1 if fails else 0)
