"""Scenario tests for the Machines panel and the boxes it draws, in two parts that each run in a process of their own (formerly the suites machines and retired_box): the machine cards, and a retired box that has no card.

Part `machines` - the Machines panel's machine cards — fixture data, a fake ssh, no live store, no network, no server.

Covers: one card per machine with its name as the bold first label (box-a, box-c, box-b, box-e from the fleet, then box-d and
box-g from [machines_panel] ssh_hosts, in config order), the package rows inside it with their state words (latest ✓, update <version>,
offline); an alert card (a failed setup step) under its machine's card, outside it; an ssh host read with ONE ssh call per host that asks every
package, a package the host lacks giving no row, a version behind the latest showing "update"; the read cached between writes, read again on
force; an unreachable host showing offline with its last versions and, if it never answered, one offline row; the script that goes over ssh
(each command in its own subshell, the executable's directory on PATH, a missing executable silent) run for real here under bash; and the
default (no ssh_hosts) changing nothing and never calling ssh; and a host that is also a fleet machine drawn as that machine's one card (ssh-probed versions, the fleet's rows, its alert card).
Also: the publisher found from the hostname (the names table, the fleet state, the hostname itself; an explicit [fleet] publisher_letter wins; fails open to a), the server's own host read by running the script here and the other hosts over ssh from it.

Part `retired_box` - a retired box: its letter is in [fleet] retired_letters, so it has no card — fixture data, no live store, no network, no server.

Covers: the Machines panel, `fleet.names()`, `fleet.machines_order()`, the versions read (`machines_state`, versions.json), the board's per-machine facts (so a failed setup on a retired box gives
no alert card) and the sessions tool's Machines list leave out the letters in [fleet] retired_letters (`fleet.drawn_letters`), also a retired letter that has a row in the names table, while
`fleet.letters()` and the readers that find a session or an owner (`fleet.sessions()`, `by_name`) still see every folder; the default (no key, an empty list) draws every folder's letter; the key's
shapes (one string, spaces around a letter, items that are not strings, a value that is not a list, a letter in another case) never raise and retire only what is named; the publisher's letter is
never left out; a change of the setting is read at the next draw. The server side is untouched: `clients.checkin` and `clients.tick` still write a retired box's folder and keep its sessions as
last known (a session gone from the box is marked gone there), and a successor of the same name on another box resolves to the running one.

The two parts set up two different instances, and each part changes module state of the code under test that the other would meet, so each part runs in a process of its own;
the file runs them one after the other, adds their check counts and exits 1 when a part fails.

    tests/run-suite machines        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("machines", "retired_box")


# ================================================================ part machines: the Machines panel's machine cards
def part_machines():
    import json, os, re, sys, pathlib, tempfile, logging, subprocess, datetime, shutil
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="machinestest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("fleet_names", f"{tmp}/names.tsv")):   # names.tsv: absent until the publisher section below writes it
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

    from stackshot.fleet import versions as ver
    from stackshot.web.ui import render as ui_render
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

    # ---- the publisher is the box the server runs on, found from the hostname; the ssh hosts are read from where it runs
    from stackshot.fleet import fleet as flt
    FL = ver._cfg.CFG.setdefault("fleet", {}); NAMES = T / "names.tsv"
    own_was, ssh_was = flt.own_hostname, list(ver._cfg.CFG["machines_panel"].get("ssh_hosts") or [])
    check("publisher: the key is unset in the example config, so what follows finds the box from its hostname", not FL.get("publisher_letter"), FL)
    flt.own_hostname = lambda: "Host-Z.example.net"
    check("publisher: no readable names table and no fleet machine of that name: the key every install had before, a", flt.publisher() == "a", flt.publisher())
    NAMES.write_text("# os hostname\tfleet name\tletter\nbox-a\tbox-a\ta\nHOST-Z\tbox-z\tz\n", encoding="utf-8")
    check("publisher: unset, the names table's row for this box gives its letter (OS hostname, any case, domain left off)", flt.publisher() == "z", flt.publisher())
    flt.own_hostname = lambda: "box-z"
    check("publisher: …or by the fleet name in that row", flt.publisher() == "z", flt.publisher())
    FL["publisher_letter"] = "b"
    check("publisher: an explicit [fleet] publisher_letter wins over the hostname", flt.publisher() == "b", flt.publisher())
    FL["publisher_letter"] = "  "
    check("publisher: a blank value is unset", flt.publisher() == "z", flt.publisher()); FL.pop("publisher_letter")
    flt.own_hostname = lambda: "stranger"
    check("publisher: a hostname the table does not list and no fleet machine answers to is its own key (lower-cased), not another box's letter", flt.publisher() == "stranger", flt.publisher())
    (T / "fleet/q").mkdir(); (T / "fleet/q/machine.json").write_text(json.dumps({"letter": "q", "fleet": "Stranger", "claude": "1.7.40"})); (T / "fleet/q/sessions.json").write_text("{}")
    check("publisher: …unless the fleet state holds a machine of that name: its letter", flt.publisher() == "q", flt.publisher())
    shutil.rmtree(T / "fleet/q")
    flt.own_hostname = lambda: ""
    check("publisher: a hostname that cannot be read fails open to a", flt.publisher() == "a", flt.publisher())
    flt.own_hostname = lambda: "box-z"; NAMES.write_text("not\ta\ttable", encoding="utf-8")
    check("publisher: a readable names table with no row of this box gives the hostname key", flt.publisher() == "box-z", flt.publisher())
    NAMES.unlink()
    check("publisher: a names table that cannot be read gives a", flt.publisher() == "a", flt.publisher())
    NAMES.write_text("HOST-Z\tbox-z\tz\n", encoding="utf-8")
    check("own host: the OS hostname and the names table's hostname and fleet name are this box; another name is not",
          flt.is_own_host("box-z") and flt.is_own_host("HOST-Z") and flt.is_own_host("host-z.example.net") and not flt.is_own_host("box-d") and not flt.is_own_host(""), flt.own_names())
    check("panel order: the publisher's name first, then the fleet by letter",
          flt.machines_order({"a": "box-a", "z": "box-z", "b": "box-c"}, []) == ["box-z", "box-a", "box-c"], flt.machines_order({"a": "box-a", "z": "box-z", "b": "box-c"}, []))

    # the server runs on box-z (a letter in the names table, no puller, so no fleet state of its own): its card is first and live with its versions; box-d is read over ssh, box-z is not
    HERE = []                                                       # every script run on this box for an ssh_hosts entry
    def fake_here(script, timeout=10):
        HERE.append(script); asked = [int(x) for x in re.findall(r"@@(\d+)", script)]
        said = {"claude code": "1.7.40 (Claude Code)", "gbrain": "gbrain 1.9.12"}
        return 0, "".join(f"@@{i}\n{said.get(PKGS[i], '')}\n" for i in asked)
    ver._run_here = fake_here; ver._cfg.CFG["machines_panel"]["ssh_hosts"] = ["box-z", "box-d", "box-g"]
    ANSWER["box-d"] = (0, {"claude code": "1.7.39 (Claude Code)", "gbrain": "gbrain 1.9.12"}); ANSWER["box-g"] = (0, {"gbrain": "gbrain 1.9.10"})
    CALLS.clear(); ver.SSH_OUT.unlink(missing_ok=True)
    doc = ver.write(force=True); hs = {h["name"]: h for h in doc["ssh_hosts"]}; sec = panel(); z = card(sec, "box-z")
    check("own host: box-z, the server's own box, is read by running the script here (once, every package asked), never over ssh; the other hosts are still read over ssh",
          len(HERE) == 1 and HERE[0].count("@@") == 2 and sorted(h for h, _ in CALLS) == ["box-d", "box-g"], (HERE, CALLS))   # the hosts are probed in parallel threads: no order
    check("own host: box-z answers: reachable, its versions in versions.json, in config order",
          [h["name"] for h in doc["ssh_hosts"]] == ["box-z", "box-d", "box-g"] and hs["box-z"]["reachable"] is True and hs["box-z"]["packages"] == {"claude code": "1.7.40", "gbrain": "1.9.12"}, doc["ssh_hosts"])
    check("publisher: box-z is the first card, once, ahead of the fleet (it has no puller and no state of its own); the others follow, the ssh-only hosts last",
          names(sec) == ["box-z", "box-a", "box-c", "box-b", "box-e", "box-d", "box-g"] and sec.count(">box-z</b>") == 1, names(sec))
    check("publisher: its card is live with its own versions (claude code from the binary, gbrain) and no offline row",
          [(r[0], r[1], r[2], r[3]) for r in rows(z)] == [("latest", "claude code", "1.7.40", "latest ✓"), ("latest", "gbrain", "1.9.12", "latest ✓")], rows(z))
    check("publisher: versions.json holds it as live with its claude version, under the key the panel's first column uses",
          doc["packages"][0]["machine_state"].get("z") == "live" and doc["packages"][0]["machines"].get("z") == "1.7.40", doc["packages"][0])
    # the same list on the box that ran the server before: it is read here and box-z over ssh
    flt.own_hostname = lambda: "box-a"; NAMES.write_text("box-a\tbox-a\ta\nHOST-Z\tbox-z\tz\n", encoding="utf-8")
    ver._cfg.CFG["machines_panel"]["ssh_hosts"] = ["box-z", "box-a"]; ANSWER["box-z"] = (0, {"claude code": "1.7.38 (Claude Code)"}); ANSWER["box-a"] = (0, {})
    CALLS.clear(); HERE.clear(); ver.SSH_OUT.unlink(missing_ok=True)
    doc = ver.write(force=True)
    check("moved: with the server on box-a, box-a is read here and box-z over ssh (the same list, read from wherever the server runs); box-a is the publisher",
          len(HERE) == 1 and [h for h, _ in CALLS] == ["box-z"] and flt.publisher() == "a" and doc["packages"][0]["machine_state"].get("a") == "live", (HERE, CALLS, flt.publisher()))
    ANSWER["box-z"] = (255, {}); doc = ver.write(force=True); hs = {h["name"]: h for h in doc["ssh_hosts"]}
    check("moved: an unreachable ssh host does not touch the box's own read", hs["box-z"]["reachable"] is False and hs["box-a"]["reachable"] is True, hs)
    # the one place that runs a host's script here: sh -c, no stdin, the host's timeout (subprocess.run replaced: nothing runs)
    import importlib; ver3 = importlib.reload(ver); seen = {}
    def fake_run2(cmd, **kw): seen["cmd"] = cmd; seen["kw"] = kw; return subprocess.CompletedProcess(cmd, 0, "@@0\nx 1.0.0\n", "")
    ver3.subprocess.run = fake_run2; rc, out = ver3._run_here("echo hi")
    check("run here: `sh -c <script>`, no stdin, the ssh timeout; its exit code and output as _ssh gives them",
          seen["cmd"] == ["sh", "-c", "echo hi"] and seen["kw"]["timeout"] == ver3.SSH_TIMEOUT and seen["kw"]["stdin"] == subprocess.DEVNULL and (rc, out) == (0, "@@0\nx 1.0.0\n"), seen)
    def boom_here(cmd, **kw): raise subprocess.TimeoutExpired(cmd, 10)
    ver3.subprocess.run = boom_here
    check("run here: a timeout is a failed read (255), not an exception", ver3._run_here("x") == (255, ""))
    flt.own_hostname = own_was; NAMES.unlink(missing_ok=True); ver = ver3; ver._ssh = good; ver._cfg.CFG["machines_panel"]["ssh_hosts"] = ssh_was

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
    return ran, fails


# ================================================================ part retired_box: a retired box has no card
def part_retired_box():
    import json, os, re, sys, pathlib, logging, shutil
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="retiredboxtest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("fleet_names", f"{tmp}/names.tsv")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^latest_lookups = true', 'latest_lookups = false', toml); assert n == 1                  # never npm or GitHub
    toml, n = re.subn(r'(?m)^ssh_hosts = \[\]', 'ssh_hosts = []', toml); assert n == 1
    toml += '\n[[machines_panel.packages]]\nname = "claude code"\nowner = ""\ninstalled = "fleet"\nlatest = "github-release:x/y"\n'
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    FLEET = T / "state/clients/fleet"                                    # the one folder the server writes and the readers read
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(FLEET))
    for d in ("store/a", "state/site", "secrets", "touch"): (T / d).mkdir(parents=True)
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
    (T / "state/site/versions.latest.json").write_text(json.dumps({"claude code": "1.7.40"}))
    NAMES = T / "names.tsv"
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"))
        if not cond: fails.append(name)

    from stackshot.fleet import fleet as flt
    from stackshot.fleet import clients
    from stackshot.fleet import versions as ver
    from stackshot.web.ui import render as ui_render
    from stackshot.web import render as txt_render
    from stackshot.web.tools import sessions as sess_tool
    from stackshot.service import fleet_events
    ver._installed_cmd = lambda cmd: "1.7.40"
    flt.publisher = lambda: "a"                                          # the box the server runs on: this test's own, whatever the host is called
    sess_tool._fleet_names = fleet_events.fleet_names                     # what register() hands the tool
    FL = flt._cfg.CFG.setdefault("fleet", {})
    def retire(v):
        if v is None: FL.pop("retired_letters", None)
        else: FL["retired_letters"] = v

    NOW = 1_800_000_000.0
    def put(L, fleet_name, **extra):
        """A machine's folder as the view writes it (machine.json and sessions.json), for the reader checks."""
        (FLEET / L).mkdir(parents=True, exist_ok=True)
        (FLEET / L / "machine.json").write_text(json.dumps({"letter": L, "fleet": fleet_name, "claude": "1.7.40", "online": {"ok": True, "since": "2026-10-20T00:00:00Z"}, **extra}))
        (FLEET / L / "sessions.json").write_text(json.dumps({f"0000000{L}-0000-0000-0000-000000000000": {"name": f"sess-{L}", "seen": "2026-10-20T00:00:00Z", "machine": L, "url": ""}}))
    def panel():
        h = ui_render.Board(str(T / "store")).render({"html"})["html"]
        sec = h[h.find('<section id="machines">'):]; return sec[:sec.find("</details>")]
    def cards(sec): return re.findall(r'<b class="lbl mh">([^<]*)</b>', sec)

    # ---- 1. the readers
    for L, nm in (("a", "box-a"), ("b", "box-b"), ("e", "box-e")): put(L, nm)
    m = json.loads((FLEET / "e/machine.json").read_text()); m["setup"] = {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "winget exited"}
    (FLEET / "e/machine.json").write_text(json.dumps(m))                 # the retired box's old failure: it must not come back as an alert card
    ver.write(force=True)
    check("default (no key): every folder is drawn, the failed box's alert on its card", cards(panel()) == ["box-a", "box-b", "box-e"] and flt.drawn_letters() == ["a", "b", "e"], cards(panel()))
    retire([])
    check("an empty list retires nothing", flt.drawn_letters() == ["a", "b", "e"] and flt.retired_letters() == frozenset())

    retire(["e"])
    ver.write(force=True); sec = panel()
    check("a retired box has no card, though its folder is there", cards(sec) == ["box-a", "box-b"] and "box-e" not in sec and "Install Claude Code" not in sec, cards(sec))
    check("fleet.names(): the retired box's folder names nothing", flt.names() == {"a": "box-a", "b": "box-b"}, flt.names())
    check("fleet.machines_order(): the retired box is not in the order", flt.machines_order() == ["box-a", "box-b"], flt.machines_order())
    check("fleet.drawn_letters() leaves the retired letter out; fleet.letters() still lists the folder", flt.drawn_letters() == ["a", "b"] and flt.letters() == ["a", "b", "e"], (flt.drawn_letters(), flt.letters()))
    ms, st = ver.machines_state()
    check("the versions read gives the retired box no version and no state", sorted(ms) == ["a", "b"] and sorted(st) == ["a", "b"], (ms, st))
    doc = json.loads((T / "state/site/versions.json").read_text()); pk = next(p for p in doc["packages"] if isinstance(p.get("machines"), dict))
    check("versions.json carries no machine for the retired box", sorted(pk["machines"]) == ["a", "b"] and sorted(pk["machine_state"]) == ["a", "b"], pk)
    check("the board's per-machine facts leave the retired box out (no alert card)", sorted(ui_render.Board(str(T / "store")).mfacts) == ["a", "b"] and sorted(txt_render.Board(str(T / "store")).mfacts) == ["a", "b"])
    listing = sess_tool._sessions_listing("").split("Sessions (")[0]               # the Machines lines (a session of the retired box is still listed under Sessions: its identity is kept)
    check("the sessions tool lists the drawn machines only", "- box-a:" in listing and "- box-b:" in listing and "box-e" not in listing, listing)
    check("what finds sessions still reads every folder: the retired box's session is in fleet.sessions() and its name resolves",
          "0000000e-0000-0000-0000-000000000000" in flt.sessions() and flt.by_name().get("sess-e") == "0000000e-0000-0000-0000-000000000000", sorted(flt.sessions()))

    NAMES.write_text("box-a-os\tbox-a\ta\nbox-b-os\tbox-b\tb\nbox-e-os\tbox-e\te\nbox-q-os\tbox-q\tq\n", encoding="utf-8")      # the retired boxes still have their rows in the names table (q has no folder)
    check("a retired letter that has a row in the names table is not named either (with a folder, or with none)", flt.names() == {"a": "box-a", "b": "box-b", "q": "box-q"} and cards(panel()) == ["box-a", "box-b", "box-q"], (flt.names(), cards(panel())))
    retire(["e", "q"])
    check("…a retired letter with a row and no folder", flt.names() == {"a": "box-a", "b": "box-b"} and cards(panel()) == ["box-a", "box-b"], (flt.names(), cards(panel())))
    retire(["e"]); NAMES.unlink()

    # ---- 2. the shapes of the key
    for label, v, want in (("one string", "e", ["a", "b"]), ("spaces around a letter", [" e "], ["a", "b"]), ("items that are not strings, an empty one", [1, None, "", "  ", "e", ["b"]], ["a", "b"]),
                           ("a value that is not a list", {"e": 1}, ["a", "b", "e"]), ("a number", 5, ["a", "b", "e"]), ("a letter in another case", ["E"], ["a", "b", "e"]),
                           ("two letters", ["b", "e"], ["a"]), ("a letter no folder has", ["z"], ["a", "b", "e"]), ("key absent", None, ["a", "b", "e"])):
        retire(v)
        try: got = flt.drawn_letters()
        except Exception as ex: got = repr(ex)
        check(f"the key as {label}: never raises, retires only what is named", got == want, got)
    retire(["b", "e"]); check("a change of the setting is read at the next draw", flt.drawn_letters() == ["a"] and flt.names() == {"a": "box-a"}, (flt.drawn_letters(), flt.names()))

    # ---- 3. the publisher is never left out
    retire(["a", "e"])
    check("a retired letter that is the publisher's own is still drawn", flt.drawn_letters() == ["a", "b"] and sorted(flt.names()) == ["a", "b"], (flt.drawn_letters(), flt.names()))
    flt.publisher = lambda: "e"
    check("…whichever letter the publisher is", flt.drawn_letters() == ["b", "e"], flt.drawn_letters())
    flt.publisher = lambda: "a"

    # ---- 4. the server writes a retired box's folder as before
    for L in ("a", "b", "e"): shutil.rmtree(FLEET / L)
    retire(["e"])
    SA, SB = "00000001-0000-4000-8000-000000000001", "00000002-0000-4000-8000-000000000002"
    NAMES.write_text("box-a-os\tbox-a\ta\nbox-b-os\tbox-b\tb\nbox-e-os\tbox-e\te\n", encoding="utf-8")
    clients.checkin("box-a-os", [], {"claude": "1.7.40"}, now=NOW)
    clients.checkin("box-e-os", [{"uuid": SA, "name": "twin"}], {"claude": "1.7.40"}, now=NOW)
    check("a retired letter's folder is written by a check-in", (FLEET / "e/machine.json").is_file() and SA in json.loads((FLEET / "e/sessions.json").read_text()), sorted(p.name for p in FLEET.iterdir()))
    clients.checkin("box-e-os", [], {"claude": "1.7.41"}, now=NOW + 30)
    row = json.loads((FLEET / "e/sessions.json").read_text())[SA]
    check("a session gone from the retired box is marked gone in its folder, not held as running", row.get("gone") and json.loads((FLEET / "e/machine.json").read_text())["claude"] == "1.7.41", row)
    clients.checkin("box-a-os", [{"uuid": SB, "name": "twin"}], {"claude": "1.7.40"}, now=NOW + 60)
    check("a successor of the same name on a drawn box resolves to the running session", flt.by_name().get("twin") == SB and not flt.running(flt.sessions()[SA]) and flt.running(flt.sessions()[SB]), flt.by_name())
    check("the retired box is still not drawn, though the server keeps writing it", flt.drawn_letters() == ["a"] and flt.letters() == ["a", "e"], (flt.drawn_letters(), flt.letters()))
    clients.tick(NOW + 90)
    check("the tick keeps writing it too", (FLEET / "e/machine.json").is_file())
    return ran, fails


MARK = "@@machines part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"machines": part_machines, "retired_box": part_retired_box}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        sys.exit(0)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: machines scenario, {total} checks")
