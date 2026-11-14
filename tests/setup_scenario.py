"""Scenario test for bin/stackshot: setup, doctor and client install on a fresh HOME — no systemd, no sudo, no network
beyond 127.0.0.1, nothing outside a temp dir.

Covers: `setup --yes` writes a config that config.py loads with the derived paths; the data repository has one commit with
RULES.md, the first page, session-names.tsv and the page registry; `pages.py registry` lists projects/getting-started; the
secrets are private (the token, oauth.env with both values empty; ui-session.key is left to the server); `install.sh render`
for that config covers the server units and the puller, not portal-sync or anchor-hub; a second setup without --force is
refused and leaves the config byte-identical; `client install --print` emits exactly the four hooks; `client install` twice
leaves settings.json as the first run wrote it, keeps a foreign hook and backs up once; `doctor --no-systemd` exits 1 and
names oauth.env; `client mint` prints only the token file's path; `client install --url --token-file` on a client HOME.
[units] scope: `setup --yes` writes scope = "user"; `doctor --no-systemd` reports lingering in user scope and says
nothing of it in system scope.
the item install fixes: setup without --yes and without a terminal refuses (exit 2); the example's page gate nags; RULES.md's
heading is instance.title; doctor reports lingering in both scopes once a user unit is installed (loginctl stubbed) and says
whether the data repository has an origin; setup with the units step (systemctl stubbed) repeats the root command at the end
when lingering stays off, and carries no "changed, not restarted" hint; `publish.py flush` with no origin commits, says
nothing was pushed and exits 0, and fails on an origin it cannot fetch; `client mint` refuses an existing name unless --rotate;
`client install --url` on a box with no config writes one from the server's `config` read (a fake server here) and leaves an
existing one alone; the puller ends within about 2 s of SIGTERM while its poll is held; `client install --print --no-puller`
adds client.py's register, seen and drain hooks.
doctor counts the page hooks the enabled stackshot Claude Code plugin carries (made-up settings and plugin files under fake HOMEs): 1 in settings + 3 in the plugin passes;
the plugin disabled, not installed or another plugin does not count; board alone is unchanged.
the item follow-up: doctor on a client machine (no oauth.env, no stackshot.service) says so on its first line and checks only the
token, the server's whoami for it (a fake server), lingering and the puller when its unit is installed, and the hooks — never
the server's units; XDG_RUNTIME_DIR unset with the user's runtime directory present is repaired by the stackshot script and by
install.sh (systemctl stubbed to need it), and left alone when set; skipped unit checks are a warning and never "all good"
with exit 0; install.sh says what to do when the user manager is out of reach; the plain flavor's Stop question names the one
page and the nag on a machine with no pages copy reads in one parenthesis.
One server per user: `setup --port` writes [server] port, from which the default base URL, client.url and the units follow;
a rerun with --force and a new port keeps the token and moves client.url; a port out of range is refused before anything is written; so is a port another user's process listens on, and doctor
says whose it is instead of reporting that user's server as ours.

    tests/run-suite setup        → exit 0 / 1"""
import json, os, re, shutil, signal, socket, stat, subprocess, sys, pathlib, tempfile, threading, time, tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="setuptest-"); T = pathlib.Path(tmp)
HOME = T / "home"; HOME.mkdir(); (T / "procnet-none").mkdir()
(T / "bin").mkdir(); (T / "bin/sudo").write_text(f"#!/bin/sh\ntouch {tmp}/sudo-called\nexit 1\n"); (T / "bin/sudo").chmod(0o755)
# loginctl: Linger as the file `linger` says (no); enabling it is refused
(T / "bin/loginctl").write_text(f'#!/bin/sh\ncase "$*" in show-user*) cat {tmp}/linger ;; *) exit 1 ;; esac\n'); (T / "bin/loginctl").chmod(0o755)
(T / "linger").write_text("no\n")
ENV = {**os.environ, "HOME": str(HOME), "STACKSHOT_URL": "http://127.0.0.1:9",   # the hooks' client reads go nowhere, never to a live server
        "USER": "tester", "STACKSHOT_SYSTEM_UNIT_DIR": f"{tmp}/etc-systemd",   # this box's own /etc/systemd/system is not the test's
       "PATH": f"{tmp}/bin:" + os.environ.get("PATH", ""),
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(HOME / ".gitconfig"),
       "STACKSHOT_PROC_NET": str(T / "procnet-none")}   # no listeners: the box's own (a live server on 8020, CI's runner beside it) never decide a check
for k in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG", "STACKSHOT_URL", "STACKSHOT_FLEET_DIR", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
          "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
    ENV.pop(k, None)
SS = os.path.join(STACK, "bin", "stackshot")
DATA = T / "data"; CFG = HOME / ".config/stackshot/stackshot.toml"; SEC = HOME / ".config/stackshot"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def ss(*args, env=None):
    return subprocess.run([SS, *args], capture_output=True, text=True, env=env or ENV, stdin=subprocess.DEVNULL)
def mode(p): return stat.S_IMODE(os.stat(p).st_mode)

# ---- 1. setup
r = ss("setup", "--yes", "--data", str(DATA), "--base-url", "http://127.0.0.1:18020", "--no-systemd")
out = r.stdout + r.stderr
check("setup exits 0", r.returncode == 0, out[-1500:])
check("setup prints the Google redirect URI and the connector URL", "http://127.0.0.1:18020/auth/callback" in out and "http://127.0.0.1:18020/mcp" in out, out[-800:])
check("setup ends with the next step", "fill oauth.env" in out and "bin/stackshot doctor" in out, out[-300:])
check("setup says the unit step was skipped", "skipped (--no-systemd)" in out, out)
check("setup set a repo-local git identity and said so", "git has no identity" in out, out)
check("setup never called sudo", not (T / "sudo-called").exists())
check("the config is at ~/.config/stackshot/stackshot.toml", CFG.is_file())

# the config, read through config.py exactly as the server and the hooks read it
r = subprocess.run([sys.executable, "-c", "from stackshot.core import config; import json; print(json.dumps({'file': str(config.PATH), 'cfg': config.CFG, "
                    "'store': str(config.path('paths','store')), 'brain': str(config.path('paths','brain')), 'secrets': str(config.secrets())}))"],
                   capture_output=True, text=True, env=ENV, cwd=STACK)
check("config.py loads it (found through HOME, no STACKSHOT_CONFIG)", r.returncode == 0, r.stderr[-500:])
c = json.loads(r.stdout) if r.returncode == 0 else {"cfg": {}, "file": "", "store": "", "brain": "", "secrets": ""}
C = c["cfg"]; D = str(DATA.resolve())
check("config.py picked that file", c["file"] == str(CFG), c["file"])
check("paths derive from --data", C.get("paths", {}).get("repo") == D and c["store"] == f"{D}/board-data" and C["paths"]["markdown"] == f"{D}/board.md"
      and C["paths"]["rules"] == f"{D}/RULES.md" and c["brain"] == f"{D}/pages" and C["paths"]["fleet_names"] == f"{D}/session-names.tsv", C.get("paths"))
check("the paths setup does not own stay as the example has them", C["paths"]["state"] == "~/.local/state/stackshot" and C["paths"]["secrets"] == "~/.config/stackshot"
      and C["paths"]["project_touch"] == "~/.claude/project-touch", C["paths"])
check("secrets resolve under the HOME", c["secrets"] == str(SEC), c["secrets"])
check("instance: owner, title, timezone, board_url", C["instance"]["owner"] == "tester" and C["instance"]["title"] == "stackshot: tester"
      and C["instance"]["board_url"] == "http://127.0.0.1:18020" and C["instance"]["timezone"], C["instance"])
check("auth: base_url, no emails, claude.ai callbacks kept", C["auth"]["base_url"] == "http://127.0.0.1:18020" and C["auth"]["allowed_emails"] == []
      and "https://claude.ai/api/mcp/auth_callback" in C["auth"]["allowed_client_redirect_uris"], C["auth"])
check("client.url = the base URL", C["client"]["url"] == "http://127.0.0.1:18020", C["client"])
check("prefixes default to [todo]", C["subject"]["prefixes"] == ["[todo] "], C["subject"])
check("no [units] scope key is written (the units are user units; the key is gone)", "scope" not in C.get("units", {}), C.get("units"))
check("no gbrain mirror; plain flavor", "mirror_repo" not in C["gbrain"] and C["gbrain"]["mirror_url"] == "" and C["pages"]["flavor"] == "plain", (C["gbrain"], C["pages"]))
ex = tomllib.loads(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
check("every section of the example is present", set(ex) <= set(C), set(ex) - set(C))
check("the example's page gate has no mode: the end-of-turn page question is retired, only keeper_currency is left (Mon Oct 12th 2026)",
      ex["page_gate"] == {"keeper_currency": "keepers"} and C["page_gate"] == {"keeper_currency": "keepers"}, (ex["page_gate"], C["page_gate"]))
r = subprocess.run([SS, "setup", "--data", str(T / "piped"), "--no-systemd"], input="me\nUTC\n", capture_output=True, text=True,
                   env={**ENV, "HOME": str(T / "pipedhome")})
check("setup without --yes and with piped stdin refuses, exit 2, and says why", r.returncode == 2
      and "stdin is not a terminal, so setup cannot ask: pass the answers as flags and add --yes" in r.stderr
      and not (T / "pipedhome/.config/stackshot/stackshot.toml").exists() and not (T / "piped").exists(), r.stdout + r.stderr)

# the data repository
git = lambda *a: subprocess.run(["git", "-C", str(DATA), *a], capture_output=True, text=True, env=ENV).stdout.strip()
check("the data repository has exactly one commit", git("rev-list", "--count", "HEAD") == "1" and git("log", "-1", "--format=%s") == "stackshot setup", git("log", "--oneline"))
check("on branch main", git("rev-parse", "--abbrev-ref", "HEAD") == "main")
check("the working tree is clean after setup", git("status", "--porcelain") == "", git("status", "--porcelain"))
tracked = git("ls-files").split("\n")
check("RULES.md, the first page, session-names.tsv and projects.json are committed",
      {"RULES.md", "pages/projects/getting-started.md", "session-names.tsv", "board-data/projects.json"} <= set(tracked), tracked)
rules = (DATA / "RULES.md").read_text(encoding="utf-8")
check("RULES.md's heading is instance.title", rules.splitlines()[0] == "# stackshot: tester", rules.splitlines()[0])
check("RULES.md: about 25 lines, plain flavor (no gbrain tools)", 15 <= len(rules.splitlines()) <= 40 and "gbrain" not in rules and "add_timeline_entry" not in rules
      and "`[todo] `" in rules and f"{D}/pages/<key>.md" in rules, len(rules.splitlines()))
page = (DATA / "pages/projects/getting-started.md").read_text(encoding="utf-8")
check("the page has Current state, the timeline marker and one dated bullet", "## Current state" in page and "<!-- timeline -->" in page
      and len(re.findall(r"(?m)^- \*\*\d{4}-\d{2}-\d{2}\*\* \| ", page)) == 1, page)
check("the page names its project on a `display-name:` line, not `steward:`", re.search(r"(?m)^display-name: \S+-getting-started$", page) and not re.search(r"(?m)^steward:", page), page[:300])
fn = (DATA / "session-names.tsv").read_text(encoding="utf-8").splitlines()
rows = [l.split("\t") for l in fn if l.strip() and not l.startswith("#")]
check("session-names.tsv: one row, hostname ⇥ name ⇥ the publisher letter", rows == [[socket.gethostname(), socket.gethostname(), "a"]], fn)
sys.path.insert(0, STACK)
r = subprocess.run([sys.executable, "-c", "from stackshot.fleet import clients; import json; print(json.dumps(clients.names_table()))"], capture_output=True, text=True, env=ENV, cwd=STACK)
check("clients.py reads that row", r.returncode == 0 and json.loads(r.stdout).get(socket.gethostname().lower()) == [socket.gethostname(), "a"], r.stdout + r.stderr[-300:])

# the page registry
(DATA / "board-data/projects.json").unlink()
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "registry"], capture_output=True, text=True, env=ENV)
reg = json.loads((DATA / "board-data/projects.json").read_text(encoding="utf-8")).get("pages", {}) if r.returncode == 0 else {}
check("pages.py registry lists projects/getting-started", r.returncode == 0 and list(reg) == ["projects/getting-started"], r.stdout + r.stderr)
g = reg.get("projects/getting-started", {})
check("the registry entry: title, keeper, active, a commit time, no mirror link", g.get("title") == "Getting started" and g.get("session") == "tester-getting-started"
      and g.get("role") == "name" and g.get("status") == "active" and g.get("updated", 0) > 0 and g.get("mirror") == "", g)
git("checkout", "--", "board-data/projects.json")

# a page inside the data repo: the keeper's settle test reads its git history relative to the pages dir
r = subprocess.run([sys.executable, "-c", "from stackshot.projects import pages; import time; print(pages.ct_at('projects/getting-started', time.time() + 600) is not None and "
                    "'## Current state' in pages.ct_at('projects/getting-started', time.time() + 600))"], capture_output=True, text=True, env=ENV, cwd=STACK)
check("pages.ct_at reads a page nested inside the data repo", r.stdout.strip() == "True", r.stdout + r.stderr[-300:])

# the board renders an item on that page with no mirror configured: the project is named, not linked to nothing
(DATA / "board-data/s").mkdir(exist_ok=True)
(DATA / "board-data/s/1.json").write_text(json.dumps({"id": "1", "subject": "[todo] try the board", "description": "The first item.", "status": "open",
                                                      "metadata": {"owner": "tester-getting-started", "project": "projects/getting-started", "next": "look at it"}}))
r = subprocess.run([sys.executable, "-c", "import json; from stackshot.web import render; from stackshot.core import config; from stackshot.web.ui import render as ui_render; d = str(config.path('paths','store')); print(json.dumps({'md': render.render(d, 'full'), 'html': (lambda b: b.html() + ''.join(b.routing_html(k) for k in b.proj))(ui_render.Board(d))}))"],
                   capture_output=True, text=True, env=ENV, cwd=STACK)
bd = json.loads(r.stdout) if r.returncode == 0 else {"md": "", "html": ""}
check("render: markdown names the page without an empty link", r.returncode == 0 and "- project: `projects/getting-started`" in bd["md"] and "](" + ")" not in bd["md"], r.stderr[-500:] or bd["md"][:600])
check("render: html has no empty href", r.returncode == 0 and 'href=""' not in bd["html"] and "getting-started" in bd["html"], r.stderr[-300:])
(DATA / "board-data/s/1.json").unlink(); (DATA / "board-data/s").rmdir()

# the secrets
check("the secrets dir is 0700", mode(SEC) == 0o700, oct(mode(SEC)))
host = socket.gethostname()
for p in (SEC / "client.token", SEC / f"client-tokens/{host}.token", SEC / "clients.json", SEC / "oauth.env", SEC / "client.url"):
    check(f"{p.name} exists and is 0600", p.is_file() and mode(p) == 0o600, oct(mode(p)) if p.exists() else "missing")
check("client.token = this box's minted token", (SEC / "client.token").read_text() == (SEC / f"client-tokens/{host}.token").read_text())
check("client.url points at the local port of the config", (SEC / "client.url").read_text().strip() == f"http://127.0.0.1:{C['server']['port']}", (SEC / "client.url").read_text())
check("the token never reached setup's output", (SEC / "client.token").read_text().strip() not in out)
oe = (SEC / "oauth.env").read_text(encoding="utf-8")
check("oauth.env: both keys, both empty, one comment line", re.findall(r"(?m)^(STACKSHOT_GOOGLE_CLIENT_(?:ID|SECRET))=(.*)$", oe) == [("STACKSHOT_GOOGLE_CLIENT_ID", ""), ("STACKSHOT_GOOGLE_CLIENT_SECRET", "")]
      and len([l for l in oe.splitlines() if l.startswith("#")]) == 1, oe)
check("ui-session.key is not written by setup (the server makes it)", not (SEC / "ui-session.key").exists())

# the units this config would install
r = subprocess.run([os.path.join(STACK, "install.sh"), "render", "--config", str(CFG)], capture_output=True, text=True, env=ENV)
units = re.findall(r"^# Rendered by install\.sh from units/(\S+)\.in", r.stdout, re.M)
check("install.sh render: the server units and the puller, no portal-sync, no anchor-hub",
      r.returncode == 0 and units == ["stackshot.service", "stackshot-reload.service", "stackshot-reload.path", "stackshot-puller.service"], units or r.stderr[-400:])
check("the rendered units carry this config", f"STACKSHOT_CONFIG={CFG}" in r.stdout)

# ---- 2. a second setup without --force
before = CFG.read_bytes()
r = ss("setup", "--yes", "--data", str(T / "other"), "--no-systemd")
check("a second setup without --force exits non-zero", r.returncode != 0, r.stdout + r.stderr)
check("…and leaves the config byte-identical", CFG.read_bytes() == before)
check("…and makes no other data repository", not (T / "other").exists())

# ---- 3. client install
r = ss("client", "install", "--print")
try: frag = json.loads(r.stdout)["hooks"]
except Exception: frag = {}
cmds = [h["command"] for ev in frag.values() for e in ev for h in e["hooks"]]
check("client install --print: exactly four hooks, one per event", r.returncode == 0 and sorted(frag) == ["PostToolUse", "SessionStart", "Stop", "UserPromptSubmit"] and len(cmds) == 4, r.stdout[-600:])
check("…each pointing at a script inside this checkout", all(f"{STACK}/client/hooks/" in c for c in cmds) and all(os.access(os.path.join(STACK, "client/hooks", re.search(r"hooks/([\w.-]+)", c).group(1)), os.X_OK) for c in cmds), cmds)
check("…PostToolUse on every MCP tool (the direct connector and a portal script alike)", frag.get("PostToolUse", [{}])[0].get("matcher") == "mcp__.*", frag.get("PostToolUse"))
check("--print wrote nothing", not (HOME / ".claude").exists())

SP = HOME / ".claude/settings.json"; SP.parent.mkdir()
foreign = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
SP.write_text(json.dumps(foreign), encoding="utf-8")
r1 = ss("client", "install", "--no-systemd")
first = SP.read_text(encoding="utf-8")
check("client install exits 0 and shows a diff", r1.returncode == 0 and "+++ " in r1.stdout and "session-start.sh" in r1.stdout, r1.stdout[-800:] + r1.stderr[-400:])
s1 = json.loads(first)
check("the four hooks are in, the foreign hook and keys kept", s1.get("model") == "x" and any(h["command"] == "echo mine" for e in s1["hooks"]["Stop"] for h in e["hooks"])
      and sum(1 for ev in s1["hooks"].values() for e in ev for h in e["hooks"] if "client/hooks/" in h["command"]) == 4, s1)
baks = sorted(p.name for p in SP.parent.glob("settings.json.bak-*"))
check("one backup of the old settings", len(baks) == 1 and json.loads((SP.parent / baks[0]).read_text()) == foreign, baks)
r2 = ss("client", "install", "--no-systemd")
check("a second client install changes nothing", r2.returncode == 0 and SP.read_text(encoding="utf-8") == first and "already" in r2.stdout, r2.stdout[-400:])
check("…and makes no second backup", len(list(SP.parent.glob("settings.json.bak-*"))) == 1)

# the hooks run: the page hook reaches stackshot/projects/pages.py, the session-start hook prints the brief or nothing, never fails
pt = subprocess.run(["bash", os.path.join(STACK, "client/hooks/project-page.sh"), "touch"], input=json.dumps({"session_id": "x", "tool_name": "Read"}),
                    capture_output=True, text=True, env=ENV)
check("project-page.sh touch runs pages.py and exits 0", pt.returncode == 0, pt.stderr[-300:])
pn = subprocess.run(["bash", os.path.join(STACK, "client/hooks/project-page.sh"), "nag"], input=json.dumps({"session_id": "x"}), capture_output=True, text=True, env=ENV)
check("project-page.sh nag exits 0 with nothing owed", pn.returncode == 0 and pn.stdout.strip() == "", pn.stdout + pn.stderr[-300:])
st = subprocess.run(["bash", os.path.join(STACK, "client/hooks/session-start.sh")], input=json.dumps({"session_id": "x", "source": "startup"}),
                    capture_output=True, text=True, env=ENV, timeout=60)
check("session-start.sh exits 0 with the server down: the brief rendered from the store, no client error in the context",
      st.returncode == 0 and "Board:" in st.stdout and "URLError" not in st.stdout and "hookSpecificOutput" not in st.stdout, st.stdout[-400:] + st.stderr[-300:])

# ---- 4. doctor
r = ss("doctor", "--no-systemd")
check("doctor --no-systemd exits 1 and names oauth.env", r.returncode == 1 and re.search(r"missing\s+oauth\.env", r.stdout) is not None, r.stdout[-1200:])
check("doctor names the empty allowed_emails", re.search(r"missing\s+auth\.allowed_emails", r.stdout) is not None, r.stdout[-800:])
check("doctor finds the four hooks and the token", "ok      Claude Code hooks" in r.stdout and "ok      this box's client token" in r.stdout, r.stdout[-800:])
check("doctor prints no secret", (SEC / "client.token").read_text().strip() not in r.stdout)
check("doctor on the server box says so on its first line", r.stdout.splitlines()[0].startswith("stackshot doctor · server box"), r.stdout[:200])
check("doctor --no-systemd reports the skipped unit checks as a warning line", re.search(r"(?m)^  warn\s+unit checks skipped: --no-systemd$", r.stdout) is not None, r.stdout[-1200:])
check("doctor reports lingering off as missing, with root's one command",
      re.search(r'missing\s+lingering for tester: no \(the units are user units\) — .*`sudo loginctl enable-linger tester`', r.stdout) is not None, r.stdout[-1200:])
check("doctor says the data repository has no origin remote", re.search(r"warn\s+data repository \S+: no origin remote", r.stdout) is not None, r.stdout[-800:])
user_doc = CFG.read_text(encoding="utf-8")
CFG.write_text(user_doc + '\n[units]\nscope = "system"\n', encoding="utf-8")                    # an older config: the scope removed
r = ss("doctor", "--no-systemd")
check('doctor with a config that still says [units] scope = "system": stops on the config line, naming the removal, exit 1',
      r.returncode == 1 and "the config does not load" in r.stdout and "removed;" in r.stdout and "oauth.env" not in r.stdout, r.stdout[-1200:])
CFG.write_text(user_doc + '\n[units]\nscope = "user"\n', encoding="utf-8")
r = ss("doctor", "--no-systemd")
check('…scope = "user" still in the file: accepted, and doctor notes the obsolete line', r.returncode == 1 and "oauth.env" in r.stdout
      and re.search(r"(?m)^  note\s+\[units\] scope in .*: the other values are no longer accepted", r.stdout) is not None, r.stdout[-1200:])
(T / "etc-systemd").mkdir(); (T / "etc-systemd/stackshot.service").write_text("[Unit]\n")
r = ss("doctor", "--no-systemd")
check("a leftover system-scope unit: doctor notes it in one line and stays the server box's doctor", r.stdout.splitlines()[0].startswith("stackshot doctor · server box")
      and re.search(r"(?m)^  note\s+\S+/etc-systemd/stackshot\.service exists: the removed system scope's unit", r.stdout) is not None, r.stdout[-1200:])
shutil.rmtree(T / "etc-systemd"); CFG.write_text(user_doc, encoding="utf-8")
# a [[brains]] prefix that names no folder in its brain's copy: doctor warns, naming the prefix, the brain and the copy; a prefix with a folder gets no such line
FB = T / "fake-brain"; (FB / "projects").mkdir(parents=True); (FB / "projects/p.md").write_text("# p\n")
subprocess.run(["git", "init", "-q", str(FB)], check=True, capture_output=True, env=ENV)
def brains_doc(prefix): return user_doc + f'\n[[brains]]\nname = "second"\npath = "{FB}"\nhome = "{T}/fb-home"\nprefixes = ["{prefix}"]\n'
CFG.write_text(brains_doc("docs/beta-"), encoding="utf-8")
r = ss("doctor", "--no-systemd")
check("doctor names a [[brains]] prefix with no folder in its brain, and goes on to the other checks",
      re.search(r"(?m)^  warn\s+\S+: \[\[brains\]\] second prefix 'docs/beta-' has no folder 'docs' in its local copy " + re.escape(str(FB)), r.stdout) is not None
      and "oauth.env" in r.stdout, r.stdout[-1500:])
CFG.write_text(brains_doc("projects/beta-"), encoding="utf-8")
r = ss("doctor", "--no-systemd")
check("doctor gives a prefix with a folder no such warning", "[[brains]]" not in r.stdout and "oauth.env" in r.stdout, r.stdout[-1500:])
CFG.write_text(user_doc, encoding="utf-8")
UD = HOME / ".config/systemd/user"; UD.mkdir(parents=True); (UD / "stackshot-puller.service").write_text("[Unit]\n")
r = ss("doctor", "--no-systemd")
check("doctor with the puller's user unit installed reports lingering, missing when off",
      re.search(r"missing\s+lingering for tester: no \(user units: stackshot-puller\.service\)", r.stdout) is not None, r.stdout[-1200:])
(T / "linger").write_text("yes\n"); r = ss("doctor", "--no-systemd")
check("…and ok when on", re.search(r"ok\s+lingering for tester: yes \(user units: stackshot-puller\.service\)", r.stdout) is not None, r.stdout[-1200:])
(T / "linger").write_text("no\n"); shutil.rmtree(HOME / ".config/systemd")
nodir = {**ENV, "HOME": str(T / "nohome")}
r = ss("doctor", "--no-systemd", env=nodir)
check("doctor without a config exits 1 and says to run setup", r.returncode == 1 and "stackshot setup" in r.stdout, r.stdout)

# ---- the plain flavor's wording (the item follow-up): no pages copy → one parenthesis
r = subprocess.run([sys.executable, "-c", "import json, time; from stackshot.projects import pages; "
                    "pages.BRAIN = '/nonexistent'; print(json.dumps(pages.describe('projects/getting-started', {'ts': int(time.time()), 'task': 's1'})))"],
                   capture_output=True, text=True, env=ENV, cwd=STACK)
wd = json.loads(r.stdout) if r.returncode == 0 else r.stderr[-300:]
check("plain, no pages copy: the nag says where the page is, without nested parentheses",
      "(edit the page `projects/getting-started.md` in a checkout of the pages repository, which this machine has none of: its Current state, and a dated line "
      "under its Timeline; commit and push)." in wd, wd)

# ---- publish.py flush with no origin remote: committed is all there is
fenv = {**ENV}
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/web/publish.py"), "flush"], capture_output=True, text=True, env=fenv, timeout=120)
check("flush with no origin remote: exit 0, says nothing was pushed", r.returncode == 0 and "no origin remote, so nothing was pushed" in r.stdout
      and "committed and pushed" not in r.stdout, r.stdout[-500:] + r.stderr[-500:])
check("…and the board is committed (clean tree)", git("status", "--porcelain") == "" and int(git("rev-list", "--count", "HEAD")) >= 2, git("status", "--porcelain"))
git("remote", "add", "origin", str(T / "no-such-remote.git"))
r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/web/publish.py"), "flush"], capture_output=True, text=True, env=fenv, timeout=120)
check("flush with an origin it cannot fetch: non-zero, and says so", r.returncode != 0 and "cannot fetch main from origin" in (r.stdout + r.stderr), r.stdout[-300:] + r.stderr[-300:])
r = ss("doctor", "--no-systemd")
check("doctor says the origin remote is set", re.search(r"ok\s+data repository \S+: origin remote set", r.stdout) is not None, r.stdout[-800:])
git("remote", "remove", "origin")

# ---- 5. client mint
r = ss("client", "mint", "laptop")
check("client mint prints only the token file's path", r.returncode == 0 and r.stdout.strip() == str(SEC / "client-tokens/laptop.token"), r.stdout + r.stderr)
check("…a 0600 file the server knows", mode(SEC / "client-tokens/laptop.token") == 0o600 and "laptop" in json.loads((SEC / "clients.json").read_text()))
tok1 = (SEC / "client-tokens/laptop.token").read_text(); sha1 = json.loads((SEC / "clients.json").read_text())["laptop"]["sha256"]
r = ss("client", "mint", "laptop")
check("client mint of a name that has a token refuses without --rotate, and changes nothing", r.returncode == 2 and "--rotate" in r.stderr
      and (SEC / "client-tokens/laptop.token").read_text() == tok1 and json.loads((SEC / "clients.json").read_text())["laptop"]["sha256"] == sha1, r.stdout + r.stderr)
r = ss("client", "mint", "laptop", "--rotate")
check("client mint --rotate replaces it and says the old file is now invalid", r.returncode == 0 and r.stdout.strip() == str(SEC / "client-tokens/laptop.token")
      and "now invalid" in r.stderr and (SEC / "client-tokens/laptop.token").read_text() != tok1 and tok1.strip() not in r.stdout + r.stderr, r.stdout + r.stderr)
r = ss("client", "mint", "bad/name")
check("client mint refuses a name with a path in it", r.returncode != 0 and not (SEC / "client-tokens/bad").exists(), r.stdout + r.stderr)

# ---- 6. another machine: client install --url --token-file on a HOME with no config, against a fake server
SETTINGS = {"instance": {"name": "stackshot", "title": "Remote board", "owner": "Remote", "timezone": "Asia/Dubai", "board_url": "https://board.example.com"},
            "pages": {"flavor": "gbrain", "dirs": ["projects", "ops"]}, "paths": {"brain": "~/remote-brain"}, "subject": {"prefixes": ["[x] "]},
            "page_gate": {"mode": "auto", "steward_currency": "stewards"}, "gbrain": {"mirror_url": "https://github.com/o/b/blob/main/{key}.md"},
            "server": {"path": "/mcp"}}
class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/client/config" and self.headers.get("Authorization", "").startswith("Bearer "): self._send(SETTINGS)
        elif self.path == "/client/whoami" and self.headers.get("Authorization", "") == "Bearer " + (SEC / "client-tokens/laptop.token").read_text().strip():
            self._send({"machine": "laptop"})
        elif self.path == "/client/whoami": self.send_response(401); self.end_headers()
        else: self.send_response(404); self.end_headers()
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/client/poll": time.sleep(30)            # a held poll with nothing to deliver
        try: self._send({"deliveries": []})
        except Exception: pass
FS = ThreadingHTTPServer(("127.0.0.1", 0), Fake); FS.daemon_threads = True; threading.Thread(target=FS.serve_forever, daemon=True).start()
FURL = f"http://127.0.0.1:{FS.server_address[1]}"
LAP = T / "laptop"; LAP.mkdir()
lenv = {**ENV, "HOME": str(LAP)}
r = ss("client", "install", "--url", FURL + "/", "--token-file", str(SEC / "client-tokens/laptop.token"), "--no-systemd", env=lenv)
ls = LAP / ".config/stackshot"
check("client install --url --token-file exits 0", r.returncode == 0, r.stdout[-600:] + r.stderr[-300:])
check("…stores the token (0600) and the URL beside it", (ls / "client.token").read_text() == (SEC / "client-tokens/laptop.token").read_text()
      and mode(ls / "client.token") == 0o600 and (ls / "client.url").read_text().strip() == FURL, sorted(os.listdir(ls)) if ls.exists() else "missing")
lc = tomllib.loads((ls / "stackshot.toml").read_text(encoding="utf-8")) if (ls / "stackshot.toml").is_file() else {}
check("…writes the client's config from the server's settings", lc.get("instance", {}).get("timezone") == "Asia/Dubai" and lc["instance"]["title"] == "Remote board"
      and lc["pages"]["flavor"] == "gbrain" and lc["paths"]["brain"] == "~/remote-brain" and lc["subject"]["prefixes"] == ["[x] "] and lc["page_gate"] == {"keeper_currency": "keepers"}
      and lc["gbrain"]["mirror_url"] == SETTINGS["gbrain"]["mirror_url"] and lc["client"]["url"] == FURL, (r.stdout[-400:], lc.get("instance"), lc.get("page_gate")))
check("…and says so, naming the timezone and flavor", "config → " in r.stdout and "timezone Asia/Dubai" in r.stdout and "flavor gbrain" in r.stdout, r.stdout[-500:])
r = subprocess.run([sys.executable, "-c", "from stackshot.projects import pages; import time; print(pages.describe('projects/x', {'ts': int(time.time()), 'task': 's1'}))"],
                   capture_output=True, text=True, env=lenv, cwd=STACK)
check("the client's nag speaks in the instance's zone and flavor", " +04 but the project page `projects/x`" in r.stdout and "add_timeline_entry" in r.stdout, r.stdout + r.stderr[-300:])
before_c = (ls / "stackshot.toml").read_bytes()
r = ss("client", "install", "--url", FURL, "--token-file", str(SEC / "client-tokens/laptop.token"), "--no-systemd", env=lenv)
check("a second client install leaves the existing config alone", r.returncode == 0 and "this machine has one; left as it is" in r.stdout and (ls / "stackshot.toml").read_bytes() == before_c, r.stdout[-400:])
L2 = T / "laptop2"; L2.mkdir()
r = ss("client", "install", "--url", FURL, "--token-file", str(SEC / "client-tokens/laptop.token"), "--no-systemd", env={**ENV, "HOME": str(L2), "STACKSHOT_CONFIG": str(CFG)})
check("with STACKSHOT_CONFIG set, client install writes no config", r.returncode == 0 and not (L2 / ".config/stackshot/stackshot.toml").exists(), r.stdout[-400:])
# the puller stops within about 2 s of SIGTERM while the server holds its poll (a line is removed only on ack, so nothing is lost)
(T / "emptyreg").mkdir()
pp = subprocess.Popen([sys.executable, os.path.join(STACK, "stackshot/fleet/puller.py"), "--registry", str(T / "emptyreg")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                      env={**lenv, "STACKSHOT_URL": FURL})
time.sleep(2.0); t0 = time.time(); pp.send_signal(signal.SIGTERM)
try: pout, perr = pp.communicate(timeout=10); took = time.time() - t0
except subprocess.TimeoutExpired: pp.kill(); pout, perr = pp.communicate(); took = 99
check("puller: SIGTERM during a held poll ends it within about 2 s", pp.returncode == 0 and took < 2.5 and "puller stopped" in pout, (pp.returncode, round(took, 2), pout[-300:], perr[-300:]))
# doctor on this client machine (the item follow-up): no oauth.env and no stackshot.service here, so only the client's half
lenv_x = {k: v for k, v in lenv.items() if k != "XDG_RUNTIME_DIR"}
r = ss("doctor", env=lenv_x); o = r.stdout
check("doctor on a client machine says so on its first line", o.splitlines()[0].startswith("stackshot doctor · client machine"), o[:300])
check("…checks the token, the server's whoami for it and the hooks: all good, exit 0", r.returncode == 0 and re.search(r"ok\s+this machine's client token", o)
      and re.search(r"ok\s+the server at " + re.escape(FURL) + r" answers whoami for this machine: laptop", o) and re.search(r"ok\s+Claude Code hooks in \S+: 4 of 4", o)
      and o.rstrip().endswith("all good"), o[-1500:])
ob = o.split("\n", 1)[1] if "\n" in o else ""      # below the first line, which says why this is a client machine
check("…and nothing of the server's: no oauth.env, no healthz, no server unit, never install.sh units", "oauth.env" not in ob and "healthz" not in o
      and "stackshot.service" not in ob and "install.sh units" not in o and "allowed_emails" not in o and "data repository" not in o, o)
check("…prints no token", (SEC / "client-tokens/laptop.token").read_text().strip() not in o + r.stderr)
# hooks the stackshot Claude Code plugin carries count when it is enabled: made-up settings and plugin files under fake HOMEs
def plug_home(name, settings_hooks, enabled, installed=True, plugin_name="stackshot@demo-market"):
    h = T / name; shutil.copytree(LAP / ".config", h / ".config")
    cl = h / ".claude"; (cl / "plugins").mkdir(parents=True)
    pdir = cl / "plugins" / "cache" / "demo" / "1.0"; (pdir / "hooks").mkdir(parents=True)
    pc = lambda verb: {"type": "command", "command": f'bash "${{CLAUDE_PLUGIN_ROOT}}/hooks/demo-project-page.sh" {verb}'}
    (pdir / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {   # SessionStart carries only a foreign hook, so the 4th comes from settings
        "SessionStart": [{"hooks": [{"type": "command", "command": "python3 other.py"}]}],
        "UserPromptSubmit": [{"hooks": [pc("nag")]}], "PostToolUse": [{"matcher": "x", "hooks": [pc("touch")]}], "Stop": [{"hooks": [pc("check")]}]}}))
    sh = {"SessionStart": [{"hooks": [{"type": "command", "command": "bash /opt/demo/client/hooks/session-start.sh"}]}]} if settings_hooks else {}
    (cl / "settings.json").write_text(json.dumps({"hooks": sh, "enabledPlugins": {plugin_name: enabled}}))
    if installed:
        (cl / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {plugin_name: [{"scope": "user", "installPath": str(pdir)}]}}))
    return {**lenv_x, "HOME": str(h)}
r = ss("doctor", env=plug_home("ph-on", True, True)); o = r.stdout
check("doctor counts the hooks an enabled stackshot plugin carries: 1 in settings + 3 in the plugin = 4 of 4, all good, exit 0",
      r.returncode == 0 and re.search(r"ok\s+Claude Code hooks in \S+: 4 of 4 \(3 of them from the stackshot plugin\)", o) and o.rstrip().endswith("all good"), o[-700:])
r = ss("doctor", env=plug_home("ph-off", True, False)); o = r.stdout
check("the plugin installed but disabled does not count: 1 of 4, missing, exit 1",
      r.returncode == 1 and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4(?! \()", o), o[-700:])
r = ss("doctor", env=plug_home("ph-uninst", True, True, installed=False)); o = r.stdout
check("the plugin enabled but with no install record does not count either", r.returncode == 1 and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4", o), o[-700:])
r = ss("doctor", env=plug_home("ph-other", True, True, plugin_name="elsewhere@demo-market")); o = r.stdout
check("an enabled plugin that is not the stackshot one does not count", r.returncode == 1 and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4", o), o[-700:])
def plug_hooks_file(name, text):
    e = plug_home(name, True, True); (pathlib.Path(e["HOME"]) / ".claude/plugins/cache/demo/1.0/hooks/hooks.json").write_text(text); return e
for i, (nm, txt) in enumerate((("invalid JSON", "{not json"), ("a list at the top level", "[1, 2]"), ('"hooks": 5', '{"hooks": {"Stop": [{"hooks": 5}]}}'),
                               ('"hooks": true', '{"hooks": {"Stop": [{"hooks": true}], "UserPromptSubmit": 5, "PostToolUse": [7]}}'), ("events as a list", '{"hooks": [1]}'))):
    r = ss("doctor", env=plug_hooks_file(f"ph-bad{i}", txt)); o = r.stdout
    check(f"a malformed plugin hooks.json ({nm}): no crash, nothing from the plugin: 1 of 4, exit 1",
          r.returncode == 1 and "Traceback" not in r.stderr and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4 — run", o), (r.stderr[-400:], o[-500:]))
bad = plug_home("ph-badsettings", False, False)
(pathlib.Path(bad["HOME"]) / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": 5}], "SessionStart": 3, "UserPromptSubmit": [9]}}))
r = ss("doctor", env=bad)
check("a settings.json whose hooks have the wrong shapes: no crash, 0 of 4", r.returncode == 1 and "Traceback" not in r.stderr
      and re.search(r"missing\s+Claude Code hooks in \S+: 0 of 4", r.stdout), (r.stderr[-400:], r.stdout[-400:]))
r = ss("doctor", env=plug_home("ph-prefix", True, True, plugin_name="stackshot-x@m")); o = r.stdout
check("a plugin named stackshot-x@m is not the stackshot plugin: it does not count", r.returncode == 1 and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4", o), o[-500:])
r = ss("doctor", env=plug_home("ph-alone", True, False, installed=False, plugin_name="unrelated@demo-market")); o = r.stdout
check("board alone (settings hooks, no stackshot plugin): the line and the exit are as before", r.returncode == 1
      and re.search(r"missing\s+Claude Code hooks in \S+: 1 of 4 — run bin/stackshot client install\n", o), o[-700:])
r = ss("doctor", env={**lenv_x, "STACKSHOT_URL": "http://127.0.0.1:9"})
check("doctor (client) with the server out of reach: missing, says why, exit 1", r.returncode == 1
      and re.search(r"missing\s+the server at http://127\.0\.0\.1:9 answers whoami for this machine: \[0\] .* — the server cannot be reached", r.stdout) is not None, r.stdout[-800:])
# a puller unit installed: lingering and the puller too, through systemctl --user, which this stub answers only with XDG_RUNTIME_DIR set right
UID = os.getuid(); RUN = T / "run"; (RUN / str(UID)).mkdir(parents=True); (T / "norun").mkdir(); (T / "xbin").mkdir()
(T / "xbin/systemctl").write_text(f'#!/bin/sh\necho "$XDG_RUNTIME_DIR|$*" >> {tmp}/systemctl.log\n'
                                  f'if [ "$1" = --user ] && [ "$XDG_RUNTIME_DIR" != "{RUN}/{UID}" ]; then echo "Failed to connect to bus: No medium found" >&2; exit 1; fi\n'
                                  'case "$2" in is-active) echo active ;; esac\nexit 0\n'); (T / "xbin/systemctl").chmod(0o755)
xenv = {**lenv_x, "PATH": f"{tmp}/xbin:" + lenv_x["PATH"]}
LUD = LAP / ".config/systemd/user"; LUD.mkdir(parents=True); (LUD / "stackshot-puller.service").write_text("[Unit]\n")
(T / "linger").write_text("yes\n")
r = ss("doctor", env={**xenv, "STACKSHOT_RUNTIME_BASE": str(RUN)}); o = r.stdout
check("XDG_RUNTIME_DIR unset, the runtime directory present: doctor repairs it and checks the puller", r.returncode == 0 and re.search(r"ok\s+stackshot-puller\.service: active", o)
      and re.search(r"ok\s+lingering for tester: yes \(user units: stackshot-puller\.service\)", o) and "skipped" not in o and o.rstrip().endswith("all good"), o[-1200:])
check("…systemctl --user saw XDG_RUNTIME_DIR = the user's runtime directory", f"{RUN}/{UID}|--user show-environment" in (T / "systemctl.log").read_text(), (T / "systemctl.log").read_text()[-400:])
r = ss("doctor", env={**xenv, "STACKSHOT_RUNTIME_BASE": str(T / "norun")}); o = r.stdout
check("no runtime directory: the skipped unit checks are a warning with what to do, never \"all good\" with exit 0", r.returncode == 1
      and "  warn    unit checks skipped: `systemctl --user` cannot reach your user manager: export XDG_RUNTIME_DIR=/run/user/$(id -u), "
          "or log in (ssh, console, su -, sudo -i)" in o and not re.search(r"(?m)^  missing", o) and "all good" not in o
      and o.rstrip().endswith("nothing missing among the checks that ran, but the unit checks were skipped (see the warning above)"), o[-1200:])
r = ss("doctor", env={**xenv, "STACKSHOT_RUNTIME_BASE": str(RUN), "XDG_RUNTIME_DIR": str(T / "elsewhere")})
check("XDG_RUNTIME_DIR already set: left as it is (here the stub refuses it, so the checks are skipped)", r.returncode == 1 and "unit checks skipped" in r.stdout
      and f"{T / 'elsewhere'}|--user show-environment" in (T / "systemctl.log").read_text(), r.stdout[-600:])
# install.sh: the same repair, and the same words when the user manager stays out of reach
lcfg = str(LAP / ".config/stackshot/stackshot.toml")
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", lcfg], capture_output=True, text=True, env={**xenv, "STACKSHOT_RUNTIME_BASE": str(T / "norun")})
check("install.sh puller with the user manager out of reach: exit 1, says what to do, installs nothing", r.returncode == 1
      and "`systemctl --user` cannot reach your user manager: export XDG_RUNTIME_DIR=/run/user/$(id -u), or log in (ssh, console, su -, sudo -i)" in r.stderr
      and (LUD / "stackshot-puller.service").read_text() == "[Unit]\n", r.stdout[-400:] + r.stderr[-400:])
r = subprocess.run([os.path.join(STACK, "install.sh"), "puller", "--config", lcfg], capture_output=True, text=True, env={**xenv, "STACKSHOT_RUNTIME_BASE": str(RUN)})
check("install.sh puller with XDG_RUNTIME_DIR unset and the runtime directory present: repairs it and installs the unit", r.returncode == 0
      and "stackshot-puller.service: installed" in r.stdout and (LUD / "stackshot-puller.service").read_text().startswith("# Rendered by install.sh"), r.stdout[-400:] + r.stderr[-400:])
(T / "linger").write_text("no\n"); shutil.rmtree(LAP / ".config/systemd")
FS.shutdown()
r = ss("client", "install", "--print", "--no-puller")
try: fragn = json.loads(r.stdout)["hooks"]
except Exception: fragn = {}
cn = [h["command"] for ev in fragn.values() for e in ev for h in e["hooks"]]
check("client install --print --no-puller: the four page hooks plus client.py's register, drain and seen", len(cn) == 7
      and any("client.sh register" in c for c in [h["command"] for e in fragn["SessionStart"] for h in e["hooks"]])
      and any("client.sh drain" in c for c in [h["command"] for e in fragn["UserPromptSubmit"] for h in e["hooks"]])
      and any("client.sh seen" in c for c in [h["command"] for e in fragn["Stop"] for h in e["hooks"]])
      and os.access(os.path.join(STACK, "client/hooks/client.sh"), os.X_OK), cn)
check("…prints no token", (SEC / "client-tokens/laptop.token").read_text().strip() not in r.stdout + r.stderr)
check("…and adds the four hooks to a settings.json it creates", sum(1 for ev in json.loads((LAP / ".claude/settings.json").read_text())["hooks"].values() for e in ev for h in e["hooks"]) == 4)
r = ss("client", "install", "--url", "https://x", "--no-systemd", env=lenv)
check("--url without --token-file is refused", r.returncode != 0)

# ---- 7. --force, and a data repository under the HOME: the config writes ~/… paths as the example does
H2 = T / "h2"; H2.mkdir(); e2 = {**ENV, "HOME": str(H2)}
ss("setup", "--yes", "--data", str(H2 / "sd"), "--no-systemd", env=e2)
c2 = H2 / ".config/stackshot/stackshot.toml"; first2 = c2.read_bytes()
r = ss("setup", "--yes", "--force", "--owner", "Someone Else", "--data", str(H2 / "sd"), "--no-systemd", env=e2)
t2 = tomllib.loads(c2.read_text(encoding="utf-8"))
check("setup --force rewrites the config", r.returncode == 0 and c2.read_bytes() != first2 and t2["instance"]["owner"] == "Someone Else", r.stdout[-500:] + r.stderr[-300:])
check("…with ~/ paths under the HOME", t2["paths"]["repo"] == "~/sd" and t2["paths"]["brain"] == "~/sd/pages" and t2["paths"]["store"] == "~/sd/board-data", t2["paths"])
check("…and commits the rewritten RULES.md as a second setup commit", subprocess.run(["git", "-C", str(H2 / "sd"), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip() == "2")
check("…keeps the minted token", "already minted" in r.stdout, r.stdout[-500:])

# ---- 8. setup with the units step (systemctl stubbed, lingering off and not allowed): the root command again at the end
H3 = T / "h3"; H3.mkdir(); (T / "sdbin").mkdir()
(T / "sdbin/systemctl").write_text("#!/bin/sh\nexit 0\n"); (T / "sdbin/systemctl").chmod(0o755)
e3 = {**ENV, "HOME": str(H3), "PATH": f"{tmp}/sdbin:" + ENV["PATH"]}
r = ss("setup", "--yes", "--data", str(H3 / "sd"), "--emails", "a@example.com", env=e3)
o3 = r.stdout + r.stderr
check("setup with units: exits 0 and installs the units", r.returncode == 0 and (H3 / ".config/systemd/user/stackshot.service").is_file(), o3[-1200:])
check("…no 'changed, not restarted' hint (setup says why the server is not started)", "changed, not restarted" not in o3 and "not started: it needs oauth.env" in o3, o3[-800:])
check("…install.sh warned about lingering, and setup repeats root's command at the end", "WARNING: lingering is off for tester" in o3
      and re.search(r"lingering is off for tester: .*Run this once as root:  sudo loginctl enable-linger tester\nfill oauth.env", o3) is not None, o3[-900:])

# ---- 9. --port: a second instance on the same box, under another account, on a port of its own (one server per user)
H4 = T / "h4"; H4.mkdir(); e4 = {**ENV, "HOME": str(H4), "USER": "bob"}
r = ss("setup", "--yes", "--port", "18030", "--data", str(H4 / "sd"), "--no-systemd", env=e4)
o4 = r.stdout + r.stderr
t4 = tomllib.loads((H4 / ".config/stackshot/stackshot.toml").read_text(encoding="utf-8")) if r.returncode == 0 else {}
check("setup --port writes [server] port", r.returncode == 0 and t4["server"]["port"] == 18030 and t4["server"]["host"] == "127.0.0.1", o4[-800:])
check("…the default base URL follows it", t4.get("auth", {}).get("base_url") == "http://127.0.0.1:18030" and t4["client"]["url"] == "http://127.0.0.1:18030"
      and "http://127.0.0.1:18030/mcp" in o4, t4.get("auth"))
check("…client.url points at that port", (H4 / ".config/stackshot/client.url").read_text().strip() == "http://127.0.0.1:18030")
r = subprocess.run([os.path.join(STACK, "install.sh"), "render", "anchor-hub.service", "--config", str(H4 / ".config/stackshot/stackshot.toml")],
                   capture_output=True, text=True, env=e4)
check("…the units render with that port (anchor-hub waits on its /healthz)", "http://127.0.0.1:18030/healthz" in r.stdout, r.stdout[-400:] + r.stderr[-300:])
r = ss("setup", "--yes", "--force", "--port", "18031", "--data", str(H4 / "sd"), "--no-systemd", env=e4)
check("setup --force --port keeps the token and moves client.url to the new port", r.returncode == 0 and "already minted: kept" in r.stdout
      and (H4 / ".config/stackshot/client.url").read_text().strip() == "http://127.0.0.1:18031", r.stdout[-600:])
r = ss("setup", "--yes", "--port", "70000", "--data", str(T / "badport"), "--no-systemd", env={**ENV, "HOME": str(T / "badporthome")})
check("setup refuses a port out of range, exit 2, before writing anything", r.returncode == 2 and "not a TCP port" in r.stdout
      and not (T / "badporthome/.config/stackshot/stackshot.toml").exists(), r.stdout + r.stderr)

# a port another user's process listens on (a fake /proc/net/tcp): setup refuses it, doctor says whose it is; our own is fine
PN = T / "procnet"; PN.mkdir()
def listen(port, uid):
    (PN / "tcp").write_text("  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
                            f"   0: 0100007F:{port:04X} 00000000:0000 0A 00000000:00000000 00:00000000 00000000 {uid:>5}        0 1 1 0 100 0 0 10 0\n")
listen(18040, os.getuid() + 4242)
e5 = {**ENV, "HOME": str(T / "h5"), "STACKSHOT_PROC_NET": str(PN)}
r = ss("setup", "--yes", "--port", "18040", "--data", str(T / "h5/sd"), "--no-systemd", env=e5)
check("setup refuses a port another user listens on, exit 2, before writing anything", r.returncode == 2 and "port 18040 is taken on this box by" in r.stdout
      and "--port" in r.stdout and not (T / "h5/.config/stackshot/stackshot.toml").exists(), r.stdout + r.stderr)
listen(18040, os.getuid())
r = ss("setup", "--yes", "--port", "18040", "--data", str(T / "h5/sd"), "--no-systemd", env=e5)
check("…and accepts it when the listener is our own (a rerun beside our running server)", r.returncode == 0, r.stdout[-500:])
listen(18031, os.getuid() + 4242)
r = ss("doctor", "--no-systemd", env={**e4, "STACKSHOT_PROC_NET": str(PN)})
check("doctor says the server port belongs to someone else rather than reporting their /healthz", r.returncode == 1
      and re.search(r"missing port 18031 belongs to .+, not to you", r.stdout) is not None and "the server answers" not in r.stdout, r.stdout[-900:])

shutil.rmtree(tmp, ignore_errors=True)
check("hermetic: nothing here read the host's sala session registry (CI runs on a box that has one)", "sessions_registry" not in sys.modules)
print(("ok" if not fails else "FAILED") + f": setup scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
