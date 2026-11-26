"""Scenario test for the agents' box over ssh (stackshot/core/agentbox.py, [agents_box] ssh) — fixture data, no network, and never a real ssh.

`ssh` is a stub executable put first on PATH. It logs its arguments, then does what a real ssh does with them: the words after the host are joined by spaces and run by a shell. It runs
them on this machine with HOME set to a folder of the test's own (the "agents box": its ~/.claude/sessions, its ~/.local/bin, its transcripts); a mode file makes it behave as a box that refuses
the connection (exit 255) or that never answers. Nothing of the host's home is read or written.

Covers: with no [agents_box] ssh (and with ssh naming this machine or a loopback address, and in a process that sets LOCAL_ONLY) every function returns what the caller had before, runs no ssh and writes no copy;
the ssh argument list (BatchMode, ConnectTimeout, no pty, the host after `--`, every word quoted: a word with spaces, quotes and a command substitution arrives as it is and runs nothing); a
box that refuses is a BoxError with the reason and a log line, and not asked again at once; a box that never answers is a BoxError at the call's own limit; the copy of a directory (live rows only,
a changed file replaced, a removed one removed, a second look inside cache_seconds makes no second call, a path under this machine's home is read under the box's home); the copy of pane liveness and prompt stamps from a box that
stops answering stands for stale_seconds and then reads as absent (unknown), while the session registry, links and lane files stay served and the `said` gate refuses when the registry copy is absent or
older than registry_max_age; one down-gate for the whole mirror (three folders against a hanging box cost one timeout, one probe per retry_seconds, one error line per outage); the copy's modes, a
remote name that climbs out of it, the remote timeout wrapper, the path_prepend filter, check_pid, two concurrent first reads, the presence check on the copy, a transcript line with U+2028; the session store and registry, the lane record and lane-names file, the CLI's registry of live panes (the dead row left out,
pane_row on the copy), the prompt stamps; the commands (the fleet tool's session list, the router's call in an empty directory made and removed on the box, the Slack command with its text on
standard input, and each of them when the box refuses); the transcripts (found and read on the box, the `said` gate checks them as it checks a local one, a session with no transcript there is
stored unchecked, a box that does not answer (or a transcript it cannot open) refuses the write with the reason, the plain-text form too, the message check's transcript lookup).

    tests/run-suite agents_box        → exit 0 / 1"""
import json, logging, os, pathlib, re, socket, stat, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="agentbox-"); T = pathlib.Path(tmp)
BOX = T / "agents-home"                    # the agents' box's home
HOME_LOCAL = os.path.expanduser("~")        # this machine's real home: only ever a name here, nothing is created under it
MARK = "<!-- fleet -->"
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
toml, n = re.subn(r'(?m)^transcripts = .*$', 'transcripts = ["~/.claude/projects"]', toml); assert n == 1      # the box's own: found there, never here
toml, n = re.subn(r'(?m)^injected_marker = ""', f'injected_marker = "{MARK}"', toml); assert n == 1
toml, n = re.subn(r'(?m)^session_links = .*$', 'session_links = "~/.local/state/fleet-store"', toml); assert n == 1
toml, n = re.subn(r'(?m)^lanes_file = .*$', 'lanes_file = "~/.local/state/lanes/lanes.tsv"', toml); assert n == 1
toml, n = re.subn(r'(?m)^login_shell = true', 'login_shell = false', toml); assert n == 1
toml, n = re.subn(r'(?m)^slack_command = ""', 'slack_command = "slackpost --channel reports"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", STACKSHOT_LANE_NAMES="~/.local/state/lanes/lane-names.json")
for k in ("STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID", "STACKSHOT_SALA"): os.environ.pop(k, None)
for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
for d in (".claude/sessions", ".claude/projects/-home-x", ".local/bin", ".local/state/fleet-store/a", ".local/state/lanes", ".local/state/stackshot/prompts"): (BOX / d).mkdir(parents=True)

# ---- the stub ssh: the "agents box" is this machine with HOME = BOX
MODE = T / "ssh-mode"; CALLS = T / "ssh-calls.log"; MODE.write_text("ok")
STUB = T / "stubbin"; STUB.mkdir()
(STUB / "ssh").write_text(f'''#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a" >> "{CALLS}"; done; echo "--END--" >> "{CALLS}"
case "$(cat "{MODE}")" in
  down) echo "ssh: connect to host agents-box port 22: Connection refused" >&2; exit 255;;
  hang) exec sleep 30;;
  slowdown) sleep 1; echo "ssh: connect to host agents-box port 22: Connection refused" >&2; exit 255;;
  slow) sleep 1;;
esac
while [ "$1" != "--" ]; do shift; done; shift      # the options, then the host, then the command words (ssh joins them with spaces and the box's shell runs the result)
shift
HOME="{BOX}"; export HOME; cd "$HOME"
exec sh -c "$*"
''', encoding="utf-8")
(STUB / "ssh").chmod(0o755)
os.environ["PATH"] = f"{STUB}{os.pathsep}{os.environ.get('PATH', '')}"
def mode(m): MODE.write_text(m)
def ncalls(): return CALLS.read_text().count("--END--") if CALLS.exists() else 0
def put(rel, text, mtime=None):
    p = BOX / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text, encoding="utf-8")
    if mtime: os.utime(p, (mtime, mtime))
    return p
def script(rel, body): p = put(rel, "#!/bin/sh\n" + body); p.chmod(0o755); return p

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
logs = []; levels = []
class _H(logging.Handler):
    def emit(self, r): logs.append(r.getMessage()); levels.append(r.levelname)
logging.getLogger("stackshot.agentbox").addHandler(_H()); logging.getLogger("stackshot.agentbox").setLevel(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as cfg, agentbox as ab, lanes as lanes_mod
from stackshot.fleet import clients, liveness as LV, sessions_registry as SR
from stackshot.anchors import anchors as anc
from stackshot.router import router
from stackshot.service import checks, gates, foryou_slack, messaging, telling
from stackshot.model import said
from stackshot.web import server  # noqa: F401  (the same import set as the other gate suites)
from fastmcp.exceptions import ToolError

def setbox(**kw):
    sec = cfg.CFG.setdefault("agents_box", {})
    for k, v in kw.items():
        if v is None: sec.pop(k, None)
        else: sec[k] = v
FAST = dict(cache_seconds=0.3, retry_seconds=0.3, timeout=4, connect_timeout=2, stale_seconds=1.0)
def fresh():
    """Forget every copy and lookup (a new look at the box), the log and the call count."""
    ab._SPECS.clear(); ab._GLOB.clear(); ab._SAID.clear(); ab._DOWN[0] = 0.0; ab._STATE.update(why="", logged=False, stale_logged=False); logs.clear(); levels.clear()
    mode("ok"); CALLS.write_text("")
def settle(): time.sleep(0.35)      # past cache_seconds

# ================================================================ 1. no setting: nothing changes
setbox(ssh=None)
check("no setting: not enabled, no host", not ab.enabled() and ab.host() == "")
check("no setting: argv is the command itself", ab.argv(["a", "b c"]) == ["a", "b c"])
check("no setting: mirror_dir and mirror_file are the paths given", ab.mirror_dir(T / "x", ("*.json",)) == T / "x" and ab.mirror_file(T / "x" / "f") == T / "x" / "f")
check("no setting: the prompt stamps are the state's own", ab.prompts_dir() == cfg.state("prompts"))
check("no setting: run runs here", ab.run(["echo", "hi"]).stdout == "hi\n")
check("no setting: check_pid is os.kill", ab.check_pid(os.getpid()) is None)
try: ab.check_pid(2 ** 22 + 12345); gone = False
except OSError: gone = True
check("no setting: check_pid raises for a process that is gone", gone)
check("no setting: down() is False and unreachable() says nothing", not ab.down() and ab.unreachable(255, "x") == "")
check("no setting: the links directory is the configured path", clients._links_dir() == pathlib.Path(HOME_LOCAL, ".local/state/fleet-store"), clients._links_dir())
check("no setting: the lane record and the lane-names file are the configured paths", checks.lanes_file() == pathlib.Path(HOME_LOCAL, ".local/state/lanes/lanes.tsv") and lanes_mod.path() == pathlib.Path(HOME_LOCAL, ".local/state/lanes/lane-names.json"))
check("no setting: no ssh was run", ncalls() == 0 and not (T / "state" / "agentbox").exists())
setbox(ssh="agents-box")
setbox(ssh=socket.gethostname())
check("ssh naming this machine is ignored", not ab.enabled() and ab.argv(["a"]) == ["a"])
setbox(ssh="me@" + socket.gethostname().split(".")[0].upper())
check("user@host naming this machine (any case, short name) is ignored too", not ab.enabled())
_short = socket.gethostname().split(".")[0]
for h_ in ("127.0.0.1", "me@127.0.0.5", "localhost", "LOCALHOST", "me@[::1]", "localhost.localdomain", f"{_short}.example.invalid"):
    setbox(ssh=h_)
    check(f"ssh naming this machine by a loopback name or address, or its short name ({h_}) is read as local", not ab.enabled() and ab.argv(["a"]) == ["a"])
# is_this_box with the machine's name injected (a test box's own hostname may be a loopback name, which hides the name branches): the FQDN, the short name, the domain that differs, the case
_me0, _lb0 = ab._ME[0], ab._loopback
ab._loopback = lambda name: False      # the loopback branch has its own checks above; here no name is looked up
try:
    ab._ME[0] = "box.lan.example"
    for h_, want, why in (("box.lan.example", True, "its full name"), ("BOX.Lan.EXAMPLE", True, "its full name in other case"), ("box", True, "its short name"), ("Me@BOX", True, "user@short name in capitals"),
                          ("box.other.example", True, "its short name under another domain"), ("me@box.other.example", True, "user@short name under another domain"),
                          ("boxer.lan.example", False, "another box whose name starts like it"), ("other.lan.example", False, "another box in its domain"), ("my-box", False, "a name that only ends like it"),
                          ("bo", False, "a prefix of its short name")):
        check(f"is_this_box with this box named box.lan.example: {h_} ({why}) is {'this box' if want else 'another box'}", ab.is_this_box(h_) is want, h_)
    setbox(ssh="me@box.other.example")
    check("host() reads a host that names this box under another domain as local", not ab.enabled() and ab.host() == "")
    setbox(ssh="other.lan.example")
    check("host() keeps a host that is another box", ab.host() == "other.lan.example")
    # the machine's own name is lower-cased when it is first read (the hostname may be set in capitals)
    ab._ME[0] = ""
    _gh = socket.gethostname
    try:
        socket.gethostname = lambda: "Box.Lan.EXAMPLE"
        check("the machine's own name is taken in lower case: its capitals-spelled name and its short name are this box", ab.is_this_box("box.lan.example") and ab.is_this_box("BOX") and ab._ME[0] == "box.lan.example", ab._ME[0])
    finally:
        socket.gethostname = _gh
finally:
    ab._ME[0], ab._loopback = _me0, _lb0
setbox(ssh="agents-box"); ab.LOCAL_ONLY = True
check("LOCAL_ONLY (the puller) ignores the setting", not ab.enabled() and ab.mirror_dir("/x") == pathlib.Path("/x"))
ab.LOCAL_ONLY = False
setbox(ssh="-oProxyCommand=x")
check("a host that starts with a dash is no host", not ab.enabled())

# ================================================================ 2. the ssh argument list
setbox(ssh="agents-box", ssh_options=["-p", "2222"], **FAST); fresh()
a = ab.argv(["sala", "sessions", "--json"])
check("argv: ssh, no pty, BatchMode, a connect timeout, our options first, then the host after --", a[0] == "ssh" and "-T" in a and "BatchMode=yes" in a and "ConnectTimeout=2" in a
      and a.index("-p") > a.index("BatchMode=yes") and a[a.index("--") + 1] == "agents-box" and len(a) == a.index("--") + 3, a)
check("argv: the command is one string, PATH extended, exec of the quoted words", a[-1].startswith("sh -c ") and "$HOME/.local/bin:$PATH" in a[-1] and "exec sala sessions --json" in a[-1], a[-1])
nasty = ["printf", "%s", "a b;'q' \"d\" $(touch " + str(T / "INJECTED") + ") `touch " + str(T / "INJECTED2") + "` \\ end"]
r = ab.run(nasty)
check("a word with spaces, quotes, a command substitution and backticks arrives as it is, and runs nothing", r.returncode == 0 and r.stdout == nasty[2] and not (T / "INJECTED").exists() and not (T / "INJECTED2").exists(), (r.stdout, r.stderr))
log = CALLS.read_text()
check("the stub saw BatchMode and -T and the host", "BatchMode=yes" in log.splitlines() and "-T" in log.splitlines() and "agents-box" in log.splitlines())
r = ab.run(["cat"], input="line one\nline \"two\" $HOME\n")
check("user text goes on standard input untouched", r.stdout == "line one\nline \"two\" $HOME\n", r.stdout)
r = ab.run(["sh", "-c", "pwd"], scratch="agentbox-test-")
check("scratch: the command runs in an empty directory made on the box, removed when it ends", re.match(r"^/.*/agentbox-test-\w{6}$", r.stdout.strip()) is not None and not os.path.exists(r.stdout.strip()), r.stdout)
try: ab.argv(["x"], scratch="a b"); bad = False
except ValueError: bad = True
check("scratch: a prefix that is not a plain word is refused", bad)
setbox(ssh_options=None)

# ================================================================ 3. a box that refuses, and one that never answers
fresh(); mode("down")
t0 = time.monotonic()
try: ab.run(["true"]); err = ""
except ab.BoxError as e: err = str(e)
check("a refusing box: BoxError with the reason", "does not answer over ssh" in err and "Connection refused" in err, err)
check("a refusing box: the error is logged and the box counts as down", any("agents box:" in l and "Connection refused" in l for l in logs) and ab.down(), logs)
check("not an OSError (a caller that reads a missing file as nothing must not read this so)", not issubclass(ab.BoxError, OSError))
check("unreachable(): says the box does not answer for exit 255 only", "does not answer" in ab.unreachable(255, "ssh: boom") and ab.unreachable(1, "x") == "" and ab.unreachable(0) == "")
fresh(); mode("hang"); setbox(timeout=1)
t0 = time.monotonic()
try: ab.run(["true"]); err = ""
except ab.BoxError as e: err = str(e)
took = time.monotonic() - t0
check("a box that never answers: BoxError at the call's own limit, not a hang", "no answer" in err and took < 10, (err, took))
setbox(**FAST)

# ================================================================ 4. the copy of a directory
fresh()
reg = pathlib.Path(HOME_LOCAL, ".claude/sessions")      # this machine's path: read under the box's home
alive = {"pid": os.getpid(), "sessionId": "cse_e1", "name": "agent-one", "kind": "interactive", "status": "idle", "statusUpdatedAt": 1700000000000, "startedAt": 1699990000000}
put(".claude/sessions/1.json", json.dumps(alive), 1700000100)
put(".claude/sessions/2.json", json.dumps({**alive, "pid": 2 ** 22 + 777, "name": "dead-one"}), 1700000100)       # its process is gone
put(".claude/sessions/3.json", "not json")
d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("copy: a path under this machine's home is read under the box's home (the local copy sits in the state)", str(d).startswith(f"{tmp}/state/agentbox/agents-box/"), d)
check("copy: only the row of a live process", sorted(p.name for p in d.glob("*.json")) == ["1.json"], list(d.glob("*")))
check("copy: the file keeps its time and its text", (d / "1.json").stat().st_mtime == 1700000100 and json.loads((d / "1.json").read_text())["name"] == "agent-one")
n = ncalls(); ab.mirror_dir(reg, ("*.json",), pid_key="pid"); ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("copy: a look inside cache_seconds makes no second call", ncalls() == n, (n, ncalls()))
ino = (d / "1.json").stat().st_ino
settle(); ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("copy: an unchanged file is not rewritten (same inode)", (d / "1.json").stat().st_ino == ino)
put(".claude/sessions/1.json", json.dumps({**alive, "status": "busy"}), 1700000200); put(".claude/sessions/4.json", json.dumps({**alive, "name": "agent-four"}), 1700000200)
settle(); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("copy: a changed file is replaced and a new one appears", json.loads((d / "1.json").read_text())["status"] == "busy" and (d / "4.json").exists())
(BOX / ".claude/sessions/4.json").unlink()
settle(); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("copy: a file the box no longer has is removed", not (d / "4.json").exists() and (d / "1.json").exists())
check("copy: no half-written file is left in the copy's temp folder", not list((T / "state/agentbox/.tmp").glob("*")))
# the readers on it
best = LV.pane_row({"agent-one"}, set(), reg)
check("pane_row reads the copy: the live pane's status and the time it changed", best is not None and best[1]["status"] == "busy" and best[0] == 1700000000.0, best)
check("pane_row: a session whose process is gone on the box is no pane", LV.pane_row({"dead-one"}, set(), reg) is None)
check("registered(): the live row, not the dead one", LV.registered({"agent-one"}, set(), reg) and not LV.registered({"dead-one"}, set(), reg))
# a box that stops answering: the last copy stands for stale_seconds, then the files read as absent
mode("down"); logs.clear()
settle(); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("a box that stopped answering: the last copy still stands", (d / "1.json").exists() and any("agents box:" in l for l in logs), logs)
time.sleep(1.1); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("past stale_seconds the files read as absent, and the log says so", not (d / "1.json").exists() and any("treated as absent" in l for l in logs), logs)
check("pane_row on the dropped copy: no pane (nothing can be told, as for a session that is not there)", LV.pane_row({"agent-one"}, set(), reg) is None)
n = ncalls(); ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("a failed box is not asked again inside retry_seconds", ncalls() == n)
mode("ok"); settle(); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("the box answers again: the copy is back and the log says so", (d / "1.json").exists() and any("answers again" in l for l in logs), logs)
put(".claude/sessions/9.json", json.dumps({**alive, "pad": "x" * 400})); setbox(max_file_bytes=260); settle(); d = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("a file larger than max_file_bytes is left out of the copy, and said", not (d / "9.json").exists() and (d / "1.json").exists() and any("max_file_bytes" in l for l in logs), logs)
check("an oversize file is no outage: the box does not count as down", not ab.down() and not ab._STATE["logged"] and any(lv == "ERROR" and "max_file_bytes" in l for lv, l in zip(levels, logs)), (ab.down(), ab._STATE, logs))
setbox(max_file_bytes=None)

# ---- a second process of the server's box starts its own copy of a folder the first one reads: the first one's files stay (the registry read empty for the length of a call, and a notice went to a session instead of being held)
import threading
regd = pathlib.Path(HOME_LOCAL, ".local/state/regtest"); PATS = ("*/sessions.json",)
fresh(); put(".local/state/regtest/a/sessions.json", '{"one": 1}', 1700000100)
d = ab.mirror_dir(regd, PATS, keep=True); f = d / "a/sessions.json"
check("a second process: the first one's copy is made", f.exists() and json.loads(f.read_text()) == {"one": 1}, list(d.rglob("*")))
ab._SPECS.clear(); mode("slow"); setbox(timeout=4)                    # a new process: its module state is empty; the box takes a second to answer
seen = []; th = threading.Thread(target=lambda: ab.mirror_dir(regd, PATS, keep=True)); th.start()
for _ in range(6): time.sleep(0.15); seen.append(f.exists())
th.join(); mode("ok")
check("a second process: while it makes its own copy the first one's file is there for every reader (not removed at its start)", all(seen) and th.is_alive() is False, seen)
check("a second process: its copy leaves the file as the box has it", json.loads(f.read_text()) == {"one": 1})
put(".local/state/regtest/a/sessions.json", '{"one": 2}', 1700000200)
(d / "b").mkdir(mode=0o700); (d / "b/sessions.json").write_text("{}"); (d / "b/sessions.json").chmod(0o600)                  # a file an earlier run left that the box does not have
ab._SPECS.clear(); settle(); ab.mirror_dir(regd, PATS, keep=True)
check("a new process's first good copy replaces what is there and removes a file the box does not have", json.loads(f.read_text()) == {"one": 2} and not (d / "b/sessions.json").exists(), (f.read_text(), list(d.rglob("*"))))
ab._SPECS.clear(); mode("down"); ab.mirror_dir(regd, PATS, keep=True)
check("a new process while the box does not answer: a kept copy (the registry, the links) stays for every reader", f.exists() and json.loads(f.read_text()) == {"one": 2})
try: ab.require_copy(regd, PATS, what="the fixture registry"); raised = None
except ab.BoxError as e: raised = str(e)
check("…and a check that must not go by an old copy still refuses it (this process made none)", raised is not None and "no copy" in raised, raised)
fresh(); put(".claude/sessions/1.json", json.dumps(alive), 1700000100); d2 = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("a copy that is not kept: made once", (d2 / "1.json").exists())
ab._SPECS.clear(); mode("down"); d2 = ab.mirror_dir(reg, ("*.json",), pid_key="pid")
check("a new process while the box does not answer: a copy that is not kept (pane liveness) is not read from a copy of unknown age", not (d2 / "1.json").exists(), list(d2.glob("*")))
fresh()

# ================================================================ 5. the stores the fleet tool keeps
fresh()
UU = "11111111-2222-4333-8444-555555555555"
put(".local/state/fleet-store/a/sessions.json", json.dumps({UU: {"name": "agent-one", "url": "https://sessions.example.com/s/one"}, "22222222-2222-4333-8444-555555555555": {"name": "x", "url": "javascript:alert(1)"}}))
put(".local/state/fleet-store/a/session-registry.json", json.dumps({"schema": 1, "machine": "a", "written": "2026-11-01T00:00:00Z", "sessions": {
    "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee": {"id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "name": "agent-one", "state": "live", "transcripts": [{"id": UU, "machine": "a", "at": "2026-11-01T00:00:00Z"}]}}}))
clients._LINKS.update(dir=None, sig=None, map={}); SR._CACHE.update(dir=None, sig=None, at=-1e9); SR._GOOD.clear()
links = clients.session_links()
check("session links: read from the box's store, a link that is not http(s) skipped", links.get(UU) == "https://sessions.example.com/s/one" and len(links) == 1, links)
check("session registry: the permanent id resolves from the box's registry", SR.resolve(UU) == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", SR.resolve(UU))
check("links and registry are one copy: one ssh call each look, not two", ncalls() == 1, ncalls())
put(".local/state/lanes/lanes.tsv", "agent-one\tsubscription-2\nother\tapi\n"); put(".local/state/lanes/lane-default", "api\n")
put(".local/state/lanes/lane-names.json", json.dumps({"lanes": [{"code": "api", "display": "Metered", "aliases": ["metered-old"]}]}))
check("lane record: the session's row on the box", checks.lane_record("agent-one") == ("subscription-2", ""), checks.lane_record("agent-one"))
check("lane record: the default beside it, from the same copy", checks.lane_record("nobody") == ("api", ""), checks.lane_record("nobody"))
check("lane names: the box's lane-names file", lanes_mod.display_name("metered-old") == "Metered" and lanes_mod.code("metered-old") == "api", (lanes_mod.display_name("metered-old"), lanes_mod.code("metered-old")))
sid = "abcdef12-0000-4000-8000-000000000001"
stamp_ = str(int(time.time()))         # taken once: a second boundary between the write and the check must not fail it
put(f".local/state/stackshot/prompts/{sid}", f"{stamp_}\n")
pd = ab.prompts_dir()
check("prompt stamps: the box's stamp file is read from the copy", (pd / sid).read_text().split()[0] == stamp_ and [f.name for f in pd.iterdir()] == [sid], list(pd.iterdir()))
import shutil; shutil.rmtree(T / "state/agentbox", ignore_errors=True)      # no copy of an earlier run is there (a copy another run left is served for a kept file: the check on a second process above)
fresh(); mode("down")
check("the store, the lane record and the stamps of a box that refuses: no file, no raise", clients.session_links() == {} and checks.lane_record("agent-one")[1] != "" and not list(ab.prompts_dir().glob("*")))

# ================================================================ 6. the commands
fresh()
script(".local/bin/sala", 'case "$1" in sessions) echo \'{"sessions": [{"name": "agent-one", "aliases": ["old-one"]}, {"name": "agent-two"}]}\';; *) echo "unknown $*" >&2; exit 2;; esac\n')
clients._LINKS.update(dir=None, sig=None, map={})
rows = anc.sala_rows()
check("sala_rows: the fleet tool's session list, run on the box (found on its PATH)", rows is not None and [r["name"] for r in rows] == ["agent-one", "agent-two"], rows)
check("sala_sessions: names and aliases", anc.sala_sessions() == ({"agent-one", "agent-two"}, {"old-one"}), anc.sala_sessions())
logs.clear(); mode("down")      # the store's copy is still fresh: the read goes on to the command
check("sala_rows: a box that refuses is None (the roles go without `live`), logged; the next read does not wait for it again", anc.sala_rows() is None and any("does not answer" in l for l in logs) and ab.down(), logs)
n = ncalls(); anc.sala_rows()
check("sala_rows: not asked again while the box counts as down", ncalls() == n)
ab._DOWN[0] = 0.0; logs.clear(); settle(); mode("ok"); anc.sala_rows(); mode("hang")      # warm the copy again, then the box stops answering mid-way
t0 = time.monotonic(); r = anc.sala_rows(timeout=1.0)
check("sala_rows: a box that never answers is None at the read's own limit, logged", r is None and time.monotonic() - t0 < 8 and any("no answer within 1 s" in l for l in logs), (time.monotonic() - t0, logs))
setbox(**FAST)
# the router's call
fresh()
script(".local/bin/claude", 'cat > "$HOME/call-stdin.txt"; printf \'{"result": "ruled from %s", "is_error": false, "usage": {"input_tokens": 3}}\' "$(pwd)"; echo "$@" > "$HOME/call-args.txt"\n')
out = router.run_call("a notice with 'quotes' and $(x) and\nnewlines", None, "sonnet")
check("router call: runs on the box, the message on its standard input, the answer parsed", out["status"] == "ok" and (BOX / "call-stdin.txt").read_text() == "a notice with 'quotes' and $(x) and\nnewlines", out)
cwd_used = out["text"].split("ruled from ")[-1]
check("router call: in an empty temporary directory made on the box (the prefix the puller knows) and removed there", os.path.basename(cwd_used).startswith("stackshot-router-") and not os.path.exists(cwd_used), cwd_used)
check("router call: its arguments reached the box's CLI whole", "--tools" in (BOX / "call-args.txt").read_text() and "--setting-sources" in (BOX / "call-args.txt").read_text())
fresh(); mode("down")
out = router.run_call("x", None, "sonnet")
check("router call: a box that refuses is a call that did not start (status spawn) with the reason, logged", out["status"] == "spawn" and "does not answer" in out["note"] and any("agents box:" in l for l in logs), (out, logs))
fresh(); mode("hang")
t0 = time.monotonic(); out = router.run_call("x", None, "sonnet", timeout=1)
check("router call: a box that never answers is the call's own timeout", out["status"] == "timeout" and time.monotonic() - t0 < 8, (out, time.monotonic() - t0))
# the For you list's Slack command
fresh()
script(".local/bin/slackpost", 'cat > "$HOME/slack-in.txt"; echo "$@" > "$HOME/slack-args.txt"\n')
txt = "urgent: pay the invoice \"today\"\n$(not run) 'and' more"
check("slack command: runs on the box, its text on standard input untouched, posted", foryou_slack._for_you_slack_post(txt) == "" and (BOX / "slack-in.txt").read_text() == txt and (BOX / "slack-args.txt").read_text().strip() == "--channel reports")
fresh(); mode("down")
res = foryou_slack._for_you_slack_post(txt)
check("slack command: a box that refuses is not posted, with the reason", "does not answer" in res, res)
fresh()

# ================================================================ 7. transcripts
fresh()
SESS, AWAY = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
PASTE = "please merge the refund branch today"
rows_ = [{"type": "user", "uuid": uid(10), "origin": {"kind": "human"}, "message": {"role": "user", "content": PASTE}, "timestamp": "2026-11-01T01:10:00Z"},
         {"type": "assistant", "uuid": uid(11), "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}},
         {"type": "user", "uuid": uid(12), "origin": {"kind": "human"}, "message": {"role": "user", "content": MARK + " " + PASTE}},
         {"type": "user", "uuid": uid(13), "origin": {"kind": "human"}, "message": {"role": "user", "content": "café — the refund of 12 dollars"}}]
put(f".claude/projects/-home-x/{SESS}.jsonl", "".join(json.dumps(r) + "\n" for r in rows_))
roots = gates._said_roots()
loc = said.locate(SESS, roots)
check("locate: the transcript is found on the box", isinstance(loc, ab.RemoteFile) and loc.path.endswith(f"/.claude/projects/-home-x/{SESS}.jsonl"), loc)
check("locate: a session with no transcript there is None; a name that is no uuid too", said.locate(AWAY, roots) is None and said.locate("agent-one", roots) is None)
check("find_entry on the box: the entry by its uuid, case aside", (said.find_entry(loc, uid(10).upper()) or {}).get("uuid") == uid(10))
check("find_by_quote on the box: the latest of his typed messages that holds the words (the marker one is not his)", said.find_by_quote(loc, "merge the refund branch", said.DEFAULT_PREFIXES, said.DEFAULT_PHRASES, MARK) == uid(10))
check("find_by_quote on the box: a message with escaped characters is parsed too", said.find_by_quote(loc, "refund of 12 dollars", said.DEFAULT_PREFIXES, said.DEFAULT_PHRASES, MARK) == uid(13))
def gate(*specs, sess=SESS):
    try: return gates.gate_said(specs[0] if len(specs) == 1 and isinstance(specs[0], str) else list(specs), sess, "home-agent"), ""
    except ToolError as e: return None, str(e)
got, why = gate({"tag": "Acked-by", "quote": "merge the refund branch today", "msg": uid(10)})
check("said gate: his message is found on the box and checked", got and got[0]["checked"] and got[0]["session"] == SESS and got[0]["msg"] == uid(10), (got, why))
got, why = gate({"tag": "Acked-by", "quote": "merge the refund branch today", "msg": uid(12)})
check("said gate: a message a tool typed in (the marker) is refused as on a local box", got is None and "typed into the pane" in why, why)
got, why = gate({"tag": "Acked-by", "quote": "something he never wrote", "msg": uid(10)})
check("said gate: a quote the message does not hold is refused", got is None and "Refused" in why, why)
got, why = gate({"tag": "Acked-by", "quote": "merge the refund branch today", "msg": uid(10)}, sess=AWAY)
check("said gate: a session with no transcript on the box is stored unchecked, and the entry says the agents box", got and got[0]["checked"] is False and "agents box" in got[0].get("why", ""), (got, why))
got, why = gate("merge the refund branch today")
check("said gate: the plain-text form finds his message on the box by its words", got and got[0]["checked"] and got[0]["msg"] == uid(10), (got, why))
fresh(); mode("down")
got, why = gate({"tag": "Acked-by", "quote": "merge the refund branch today", "msg": uid(10)})
check("said gate, box refusing: the write is REFUSED with the reason, never stored unchecked", got is None and why.startswith("Refused: said[0] (Acked-by)") and "could not be read from the box" in why and "not stored unchecked" in why, (got, why))
check("said gate, box refusing: and the reason is in the log", any("agents box:" in l for l in logs), logs)
fresh(); mode("down")
got, why = gate("merge the refund branch today")
check("said gate, box refusing: the plain-text form is refused too", got is None and "Refused: said:" in why and "could not be read from the box" in why, (got, why))
fresh(); put(f".claude/projects/-home-x/{uid(50)}.jsonl", "x\n"); (BOX / f".claude/projects/-home-x/{uid(50)}.jsonl").chmod(0)
if os.geteuid() != 0:
    got, why = gate({"tag": "Acked-by", "quote": "x", "msg": uid(10)}, sess=uid(50))
    check("said gate: a transcript the box cannot open (no right to it) is refused loudly, not unchecked", got is None and "Refused" in why and "cannot open" in why, (got, why))
(BOX / f".claude/projects/-home-x/{uid(50)}.jsonl").chmod(0o644)
# the message check's transcript lookup
fresh()
check("message check: a transcript id that ran on the box is known", messaging._transcript_here(SESS) and not messaging._transcript_here(AWAY))
fresh(); mode("down")
check("message check: a box that does not answer is no reason to refuse (it reads as known)", messaging._transcript_here(AWAY) is True)
fresh()

# ================================================================ 8. a silent box: what is kept, what is dropped, and what refuses
def resetreg():
    SR._CACHE.update(dir=None, sig=None, at=-1e9); SR._GOOD.clear(); clients._LINKS.update(dir=None, sig=None, map={})
PERM = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
put(f".claude/projects/-home-x/{UU}.jsonl", "".join(json.dumps(r) + "\n" for r in rows_))      # the transcript of the registry's session "agent-one"
SAY = {"tag": "Acked-by", "quote": "merge the refund branch today", "msg": uid(10)}
setbox(**{**FAST, "stale_seconds": 0.2}); fresh(); resetreg(); mode("ok")
got, why = gate(SAY, sess="agent-one")
check("a session given by name is resolved from the box's registry and its transcript checked", got and got[0]["checked"] and got[0]["session"] == UU, (got, why))
check("lane record read while the box answers", checks.lane_record("agent-one") == ("subscription-2", ""))
mode("down"); time.sleep(2.2); resetreg()      # 10 x stale_seconds
got, why = gate(SAY, sess="agent-one")
check("box down for 10x stale_seconds: a `said` write by session NAME is refused, not stored unchecked", got is None and why.startswith("Refused: said[0] (Acked-by)") and "could not be read from the box" in why, (got, why))
got, why = gate("merge the refund branch today", sess="agent-one")
check("box down for 10x stale_seconds: the plain-text form by name is refused too", got is None and "Refused: said:" in why and "could not be read from the box" in why, (got, why))
check("the registry copy is kept past stale_seconds: the name still resolves", SR.resolve("agent-one") == PERM, SR.resolve("agent-one"))
check("the links copy is kept past stale_seconds", clients.session_links().get(UU) == "https://sessions.example.com/s/one", clients.session_links())
lr_ = checks.lane_record("agent-one")
check("the lane record is not kept past stale_seconds: a silent box gives no lane (the check cannot be made), never the old one", lr_[0] == "" and "cannot be checked now" in lr_[1] and checks.lane_on("agent-one", "subscription-2")[0] is False and checks.lane_on("agent-one", "subscription-2")[1] != "", lr_)
check("the lane-names file (display names only) is kept past stale_seconds", lanes_mod.code("metered-old") == "api")
check("a kept copy served stale is flagged in the log, once", sum("is served from a copy" in l for l in logs) == 1 and not any("treated as absent" in l and "fleet-store" in l for l in logs), logs)
# never copied: refused with the reason
fresh(); resetreg(); mode("down")
got, why = gate(SAY, sess="agent-one")
check("no copy of the registry was ever made: refused, naming why", got is None and "Refused" in why and "no copy of the session registry" in why, (got, why))
got, why = gate(SAY)
check("and a session given as a transcript id is refused too (nothing is stored unchecked)", got is None and "Refused" in why, (got, why))
# older than registry_max_age
fresh(); resetreg(); mode("ok"); clients.require_links_copy()
mode("down"); setbox(registry_max_age=0.5); time.sleep(0.8); resetreg()
got, why = gate(SAY, sess="agent-one")
check("a registry copy older than registry_max_age: refused, saying how old", got is None and "Refused" in why and "old and the agents box has not answered since" in why, (got, why))
mode("ok"); settle(); resetreg()
got, why = gate(SAY, sess="agent-one")
check("the box answers again: the same write goes through, checked", got and got[0]["checked"], (got, why))
setbox(registry_max_age=None)
# a name the (fresh enough) copy does not hold, the box silent: nothing resolved is no ground for storing unchecked
NEW = "agent-newer-than-the-copy"
fresh(); resetreg(); mode("ok"); clients.require_links_copy(); mode("down"); time.sleep(0.4); resetreg()
got, why = gate(SAY, sess=NEW)
check("a name the registry copy lacks while the box is silent: the write is refused, saying the box could not be reached", got is None and why.startswith("Refused: said[0] (Acked-by)") and "could not be read from the box" in why and "does not answer" in why, (got, why))
got, why = gate("merge the refund branch today", sess=NEW)
check("and the plain-text form of it is refused too", got is None and "Refused: said:" in why and "does not answer" in why, (got, why))
mode("ok"); settle(); resetreg()
got, why = gate(SAY, sess=NEW)
check("the box answers and has no such session: stored unchecked, as before", got and got[0]["checked"] is False, (got, why))
got, why = gate("merge the refund branch today", sess=NEW)
check("and the plain-text form of it too", got and got[0]["checked"] is False, (got, why))
# with the setting off the new check is no check
setbox(ssh=None)
try: clients.require_links_copy(); okoff = True
except Exception: okoff = False
check("no setting: require_links_copy is a no-op", okoff)
setbox(ssh="agents-box")

# liveness and prompt stamps: dropped when stale, and that reads as unknown, never as a pane that is gone
fresh(); mode("ok")
put(".claude/sessions/6.json", json.dumps({**alive, "name": "agent-six", "sessionId": "cse_e6", "status": "idle", "statusUpdatedAt": 1700000500000}))
put(".local/state/stackshot/prompts/cse_e6", f"{int(time.time())}\n")
row = LV.pane_row({"agent-six"}, set(), reg)
check("before the silence: the pane is idle and the stamp says he is there", row and LV.status(row)[0] == "idle" and LV.is_idle(*LV.status(row)) and telling.presence_here("agent-six", idx={}), (row,))
mode("down"); time.sleep(0.5); ab.mirror_dir(reg, ("*.json",), pid_key="pid"); ab.prompts_dir()
row = LV.pane_row({"agent-six"}, set(), reg)
check("liveness dropped when stale reads as unknown (no row, status empty, not idle), not as a pane that is gone", row is None and LV.status(row) == ("", 0.0) and not LV.is_idle(*LV.status(row)), row)
check("the prompt stamps dropped when stale read as no stamp (not there)", not list(ab.prompts_dir().glob("*")) and telling.presence_here("agent-six", idx={}) is False)
check("both drops are in the log", sum("treated as absent" in l for l in logs) == 2, logs)

# one down-gate for the whole mirror
dirs = [pathlib.Path(HOME_LOCAL, ".claude/sessions"), pathlib.Path(HOME_LOCAL, ".local/state/lanes"), pathlib.Path(HOME_LOCAL, ".local/state/fleet-store")]
setbox(**{**FAST, "timeout": 1}); fresh(); mode("hang")
t0 = time.monotonic()
for d_ in dirs: ab.mirror_dir(d_, ("*",))
took = time.monotonic() - t0
check("a hanging box: three first reads of three folders cost about one timeout, not three (serial was 18 s)", took < 9 and ncalls() == 1, (took, ncalls()))
t0 = time.monotonic()
try: ab.glob("~/.claude/projects/*/x.jsonl"); gl = ""
except ab.BoxError as e: gl = str(e)
check("a transcript lookup respects the down-gate: at once, no new call", gl and time.monotonic() - t0 < 1 and ncalls() == 1, (gl, ncalls()))
try: said.locate(SESS, roots); lo = ""
except ab.BoxError as e: lo = str(e)
check("and so does the transcript locate of the said gate", lo and ncalls() == 1, (lo, ncalls()))
setbox(**FAST); fresh(); mode("down")
for d_ in dirs: ab.mirror_dir(d_, ("*",))
check("a refusing box: three folders, one call, and ONE error line for the whole mirror", ncalls() == 1 and sum(lv == "ERROR" for lv in levels) == 1, (ncalls(), levels, logs))
time.sleep(0.4)
for d_ in reversed(dirs): ab.mirror_dir(d_, ("*",))
check("after retry_seconds one probe goes through for all three, not one each", ncalls() == 2 and sum(lv == "ERROR" for lv in levels) == 1, (ncalls(), levels))
mode("ok"); time.sleep(0.4)
for d_ in dirs: ab.mirror_dir(d_, ("*",))
check("the box answers: each folder is copied once, and the log says so once", ncalls() == 5 and sum("answers again" in l for l in logs) == 1 and not ab.down(), (ncalls(), logs))
# log volume and the bound of the table of texts
logs.clear(); levels.clear()
for i in range(1000): ab._note(f"note {i}")
check("the table of logged texts is bounded", len(ab._SAID) <= 256, len(ab._SAID))
logs.clear(); ab._SAID.clear(); ab._note("same"); ab._note("same")
check("the same text is logged once a minute", logs == ["agents box: same"], logs)
# the copy's lock covers the drop
fresh(); mode("ok"); ab.mirror_dir(reg, ("*.json",), pid_key="pid")
sp = next(iter(ab._SPECS.values())); sp.ok -= 1000
sp.lock.acquire()
try: ab._expire(sp, time.monotonic()); held = (not sp.dropped) and bool(sp.files)
finally: sp.lock.release()
check("_expire does not run while a refresh holds the copy's lock", held)
ab._expire(sp, time.monotonic())
check("_expire under no refresh drops the stale copy", sp.dropped and not sp.files)

# ================================================================ 9. the copy's folder and files, a name that climbs, the command's wrapper, the settings, the pid, the first read, the readers
fresh(); mode("ok")
ab.mirror_dir(reg, ("*.json",), pid_key="pid")
root_ = T / "state" / "agentbox"
modes_ = {str(q.relative_to(root_)): stat.S_IMODE(q.stat().st_mode) for q in [root_, *root_.rglob("*")]}
check("the mirror folder and every folder in it are 0700, every copied file 0600", modes_ and all(m == (0o700 if (root_ / k).is_dir() else 0o600) for k, m in modes_.items()), modes_)
# a remote name that climbs out of the copy is never written
fresh()
trav = pathlib.Path(HOME_LOCAL, ".local/state/traversal-box")
evil = {"files": {"../ESC1": ["x", 1700000000000000000], str(T / "ESC-abs"): ["x", 1], "a/../../ESC2": ["x", 1], "..": ["x", 1], "": ["x", 1], "ok.json": ["{}", 1700000000000000000]}, "skipped": []}
before_ = {str(q) for q in root_.rglob("*")}
real_call = ab._call
ab._call = lambda spec, what: json.dumps(evil)
try: dt_ = ab.mirror_dir(trav, ("*",))
finally: ab._call = real_call
new_ = sorted(str(pathlib.Path(q).relative_to(root_)) for q in {str(q) for q in root_.rglob("*")} - before_)
check("a remote name with .., an absolute name, a/../..: skipped, nothing outside the copy is written, the good name is", (dt_ / "ok.json").exists() and not (T / "ESC-abs").exists()
      and new_ == [str(dt_.relative_to(root_)), str((dt_ / "ok.json").relative_to(root_))] and [q.name for q in dt_.iterdir()] == ["ok.json"], (new_, list(dt_.iterdir())))
# the remote timeout wrapper
check("the remote command runs under timeout -k", "timeout -k 5 7 true" in ab._remote_command(["true"], remote_timeout=7) and "timeout" not in ab._remote_command(["true"]))
fresh(); ab.run(["true"], timeout=9)
check("a call over ssh carries its limit to the box (timeout -k 5 9)", "timeout -k 5 9 true" in CALLS.read_text(), CALLS.read_text())
# path_prepend: only safe words
setbox(path_prepend="~/bin:/opt/x y:$(touch " + str(T / "PWN") + "):~/ok:`id`:a;b:\"q\":/usr/local/bin")
check("path_prepend: a word with a space, a substitution, a backtick, a semicolon or a quote is dropped, the others stay", ab._path_prefix() == "$HOME/bin:$HOME/ok:/usr/local/bin", ab._path_prefix())
setbox(path_prepend="$(id);`x`")
check("path_prepend: nothing safe, no PATH line at all", ab._path_prefix() == "" and "PATH=" not in ab._remote_command(["true"]), ab._remote_command(["true"]))
r = ab.run(["true"]); check("and the command still runs", r.returncode == 0)
setbox(path_prepend=None)
# the pid is asked of nobody here when the box is set
kills = []; real_kill = os.kill
os.kill = lambda pid, sig: kills.append((pid, sig))
try:
    setbox(ssh=None); ab.check_pid(4242); off_ = list(kills)
    setbox(ssh="agents-box"); kills.clear(); ab.check_pid(4242); on_ = list(kills)
finally:
    os.kill = real_kill
check("check_pid asks this machine when the setting is off, and not when it is on (the box's rows were filtered on the box)", off_ == [(4242, 0)] and on_ == [], (off_, on_))
# two first reads at once make one call, and neither returns an empty folder
fresh(); mode("slow"); put(".claude/sessions/1.json", json.dumps(alive), 1700000100)
import threading
res_ = []
def first_read(): res_.append(sorted(q.name for q in ab.mirror_dir(reg, ("*.json",), pid_key="pid").glob("*.json")))
th_ = [threading.Thread(target=first_read) for _ in range(2)]
[t.start() for t in th_]; [t.join() for t in th_]
check("two concurrent first reads: one ssh call, and both read the copy (the second waited for it)", ncalls() == 1 and len(res_) == 2 and all("1.json" in r_ for r_ in res_), (ncalls(), res_))
# the presence check reads the copy of the box's stamps, not this machine's
fresh(); mode("ok")
put(".claude/sessions/5.json", json.dumps({**alive, "name": "agent-five", "sessionId": "cse_e5"}))
put(".local/state/stackshot/prompts/cse_e5", f"{int(time.time())}\n")
check("presence_here reads the stamp from the box's copy (none exists on this machine)", not (cfg.state("prompts") / "cse_e5").exists() and telling.presence_here("agent-five", idx={}) is True)
check("and a pane with no stamp on the box is not there", telling.presence_here("agent-one", idx={}) is False)
os.utime(BOX / ".local/state/stackshot/prompts/cse_e5", (1, 1)); (BOX / ".local/state/stackshot/prompts/cse_e5").write_text("1000\n"); settle()
check("a stale stamp is not presence", telling.presence_here("agent-five", idx={}) is False)
# a transcript line with U+2028 and U+0085 inside it is one line
fresh(); mode("ok")
ODD = "caf\u2028e \u0085 refund of 7 dollars"
put(f".claude/projects/-home-x/{uid(70)}.jsonl", json.dumps({"type": "user", "uuid": uid(71), "origin": {"kind": "human"}, "message": {"role": "user", "content": ODD}}, ensure_ascii=False) + "\n"
    + json.dumps({"type": "user", "uuid": uid(72), "origin": {"kind": "human"}, "message": {"role": "user", "content": "refund again"}}) + "\n")
loc2 = said.locate(uid(70), roots)
lines_ = ab.grep_lines(loc2, all_of=("refund",))
check("grep_lines cuts at newlines only: a line with U+2028 and U+0085 in it comes back whole", len(lines_) == 2 and json.loads(lines_[0])["message"]["content"] == ODD, lines_)
check("and its entry and its quote are found", (said.find_entry(loc2, uid(71)) or {}).get("uuid") == uid(71) and said.find_by_quote(loc2, "refund of 7 dollars", said.DEFAULT_PREFIXES, said.DEFAULT_PHRASES, MARK) == uid(71))

# ================================================================ 9b. no ssh while the item lock is held (a silent box must not stall every write of every item)
import threading
from stackshot.service import update as upd, writes as WR
setbox(ssh="agents-box", **FAST); fresh(); resetreg(); mode("ok")
LOCK = WR.ITEM_LOCK
NOPE = "~/.claude/projects/*/00000000-0000-4000-8000-0000000000ff.jsonl"
# (1) a thread that holds the item lock sends nothing to the box: a lookup, a command, a copy that is due
ab.glob(f"~/.claude/projects/*/{SESS}.jsonl"); locd = said.locate(SESS, roots); clients.require_links_copy(); settle(); fresh(); resetreg()
errs_ = []
with LOCK:
    for what_, fn_ in (("glob", lambda: ab.glob(NOPE)), ("grep_lines", lambda: ab.grep_lines(locd, all_of=("refund",))), ("run", lambda: ab.run(["true"]))):
        try: fn_(); errs_.append((what_, "no error"))
        except ab.BoxError: pass
    d_ = ab.mirror_dir(reg, ("*.json",), pid_key="pid"); settle(); ab.mirror_dir(reg, ("*.json",), pid_key="pid"); down_in = ab.down()
check("under the item lock a lookup, a command and a copy that is due make no ssh call, and a lookup or command is a BoxError", ncalls() == 0 and not errs_ and down_in, (ncalls(), errs_, down_in))
check("outside the lock the box is asked again as before", not ab.down() and ab.glob(NOPE) == [] and ncalls() == 1, ncalls())
# (2) the said write: the box is slow (1 s a call); an unrelated write must not wait for it, and the gate under the lock sends nothing
fresh(); resetreg(); mode("slow"); setbox(**{**FAST, "cache_seconds": 30, "timeout": 10})
seen = {}; stored = []
def stub_update(item_id, said=None, sender="", owner="", status=""):
    """What update_unlocked does with `said`, run under the lock update_item takes."""
    seen["held"] = LOCK._is_owned(); n0 = ncalls()
    stored.append(gates.gate_said(said, sender, "home-agent"))
    seen["under_lock_calls"] = ncalls() - n0
    return "ok"
real_unlocked = upd.update_unlocked; upd.update_unlocked = stub_update
slow_res = []
def slow_write():
    try: slow_res.append(upd.update_item("a1", said=[SAY], sender="agent-one"))
    except Exception as e: slow_res.append(repr(e))
t_ = time.monotonic(); thr = threading.Thread(target=slow_write); thr.start(); time.sleep(0.4)
t1_ = time.monotonic()
with LOCK: other_wait = time.monotonic() - t1_
thr.join(); took_ = time.monotonic() - t_
upd.update_unlocked = real_unlocked
check("a said write against a slow box: an unrelated item write is not held up (took %.2f s, the said write %.2f s)" % (other_wait, took_), other_wait < 1.0 and took_ > 1.5, (other_wait, took_))
check("…and the said write itself went through, checked, from the answers kept before the lock", slow_res == ["ok"] and stored and stored[0][0]["checked"] and stored[0][0]["session"] == UU, (slow_res, stored))
check("…and the gate under the lock made no ssh call at all", seen.get("held") is True and seen.get("under_lock_calls") == 0, seen)
# the same write when the box does not answer: refused with the reason, the lock was free for others meanwhile
fresh(); resetreg(); mode("slowdown"); setbox(**{**FAST, "retry_seconds": 5}); stored.clear(); slow_res.clear(); seen.clear()
upd.update_unlocked = stub_update
t_ = time.monotonic(); thr = threading.Thread(target=slow_write); thr.start(); time.sleep(0.4)
t1_ = time.monotonic()
with LOCK: other_wait = time.monotonic() - t1_
thr.join(); upd.update_unlocked = real_unlocked
check("a said write against a box that refuses after a second: refused with the reason, and another write was not held up (%.2f s)" % other_wait,
      other_wait < 1.0 and len(slow_res) == 1 and "could not be read from the box" in slow_res[0] and not stored, (other_wait, slow_res, stored))
# the lookups the write did not make before the lock are an error under it, not an ssh call
fresh(); resetreg(); mode("ok"); setbox(**{**FAST, "cache_seconds": 30}); n0 = ncalls()     # the two writes' calls are counted, so no copy may expire between them however long the first one takes
upd.update_unlocked = stub_update; stored.clear()
try: upd.update_item("a1", said=[], sender="agent-one"); upd.update_item("a1", said=[SAY], sender="agent-one")
finally: upd.update_unlocked = real_unlocked
check("a healthy box: the write's lookups are made once, before the lock (3 calls: the registry copy, the transcript list, the transcript read)", stored and stored[-1] and stored[-1][0]["checked"] and seen["under_lock_calls"] == 0 and ncalls() - n0 <= 4, (ncalls() - n0, seen))
# (3) a name the box has no file for is asked once within cache_seconds (an empty answer is kept too)
fresh(); mode("ok"); setbox(**{**FAST, "cache_seconds": 5})
ab.glob(NOPE); ab.glob(NOPE); n_ = ncalls()
check("an empty list of files is kept for cache_seconds: one call for two lookups", n_ == 1, n_)
ab._GLOB[NOPE] = (time.monotonic() - 10, []); ab.glob(NOPE)
check("…and asked again after cache_seconds", ncalls() == 2, ncalls())
setbox(**FAST)
# (4) a refresh under way: a check that needs the box answering waits for its outcome (and is never passed on the copy alone)
fresh(); resetreg(); mode("ok"); clients.require_links_copy(); settle(); mode("slowdown"); setbox(**{**FAST, "cache_seconds": 0.3, "retry_seconds": 5})
rt_ = threading.Thread(target=clients._links_dir); rt_.start(); time.sleep(0.3)
t_ = time.monotonic()
try: clients.require_links_copy(answering=True); r4 = "passed"
except ab.BoxError as e: r4 = str(e)
w4 = time.monotonic() - t_; rt_.join()
check("require_copy(answering) while a copy is being made waits for it and takes its outcome (the box died: BoxError, waited %.2f s)" % w4, r4.startswith("the agents box does not answer") and w4 > 0.3, (r4, w4))
fresh(); resetreg(); mode("ok"); clients.require_links_copy(); settle(); mode("slowdown")
rt_ = threading.Thread(target=clients._links_dir); rt_.start(); time.sleep(0.3); n0 = ncalls()
with LOCK:
    try: clients.require_links_copy(answering=True); r4b = "passed"
    except ab.BoxError as e: r4b = str(e)
rt_.join()
check("under the item lock, a copy being made and no answer of the box in this write: not answering, nothing is waited for", "being made" in r4b, r4b)
mode("ok"); fresh(); resetreg(); setbox(**FAST)
# (5) a registry file left out for its size: the copy is no whole registry
big_ = put(".local/state/fleet-store/b/sessions.json", json.dumps({"pad": "x" * 3000})); setbox(**{**FAST, "max_file_bytes": 1000})
try: clients.require_links_copy(); r5 = "passed"
except ab.BoxError as e: r5 = str(e)
check("a registry file larger than max_file_bytes: the said gate's copy check refuses, naming it", "max_file_bytes" in r5 and "sessions.json" in r5, r5)
big_.unlink(); setbox(max_file_bytes=None, **FAST); settle(); resetreg()
try: clients.require_links_copy(); r5b = "passed"
except ab.BoxError as e: r5b = str(e)
check("…and passes again once the file is gone", r5b == "passed", r5b)
# (6) no word of the user's text and no message id in the remote command line: the request goes on standard input
fresh(); mode("ok"); ab.grep_lines(locd, all_of=("refund",), any_of=(uid(10), "paste"), ci=True)
calls_ = CALLS.read_text()
check("a transcript read: the quote's word and the message id are not in the remote command line (ssh arguments)", "refund" not in calls_ and uid(10) not in calls_ and "paste" not in calls_ and "python3" in calls_, calls_[:600])
fresh()

# ================================================================ 10. the setting off again: nothing was left on
setbox(ssh=None)
ab._SPECS.clear(); CALLS.write_text("")
check("the setting removed: the readers read their own paths again and run no ssh", clients._links_dir() == pathlib.Path(HOME_LOCAL, ".local/state/fleet-store") and said.locate(SESS, roots) is None and ncalls() == 0)

print(f"agents_box: {len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
