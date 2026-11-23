"""Scenario test for host words (stackshot/core/config.py `host`, `get`, `reload`; [hosts] lookup, timeout, cache_seconds) — a stub lookup command written to a scratch folder, no network, no real machine.

A setting that names a machine may name a role instead, `host:<role>`; the instance says how a role is looked up. The stub logs every call (its arguments) and answers as a mode file says.

Covers: a plain value, a number, a table and a list of plain items come back as they are (the same object); `host:<role>` is resolved at the leaf of get(), each string item of a list is resolved and the plain
ones are kept, a table is not touched even when it holds a host word; `config.host()` resolves one value and returns any other unchanged; the cache (one call for many reads inside cache_seconds, a new one after it,
a role of its own each); a later failed lookup keeps the last good value and is tried again after 5 seconds, not at every read, and a recovery shows; no `[hosts] lookup`, a lookup with no {role}, a command
that is not found, a first lookup that fails, and a lookup that is a host word itself all leave the word as written (never "" and never a guess) and never raise or recurse; what a lookup may print (the first
line, stripped; an empty line, spaces inside, a colon, a leading "-" and a non-zero exit are failures); a lookup that never answers is ended within the timeout and its process is gone, and so is a child it left holding its output (the process group is killed); a lookup that prints without end is cut at 4096 bytes and ended; the lookup runs without
a shell (a template word with shell characters runs nothing, {role} is replaced inside a longer word, `~` is expanded); the role's own characters (a role with a space, a colon, `;`, `$(`, a leading `-` is no
host word and runs nothing); two threads asking one role cause one lookup, and a slow role does not hold up another; one stderr line per failure streak; reload() makes every answer due, clears the failure marks, keeps the last good hosts and takes the new lookup; each of the four
readers resolves (`[project_agent] form_machines` through the form gate's helper, `[steps] bash_host`, `[agents_box] ssh`, `[machines_panel] ssh_hosts`), and `config.py get` on the command line.

    tests/run-suite config_hosts        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, socket, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="confighosts-"); T = pathlib.Path(tmp)
HOME_WAS = os.environ.get("HOME")
LOG, MODE, SENT = T / "lookup-calls.log", T / "lookup-mode", T / "sentinel"
STUB, STUB2 = T / "where-is", T / "where-else"
MODE.write_text("ok")
STUB.write_text(f'''#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a" >> "{LOG}"; done; echo "--" >> "{LOG}"
case "$(cat "{MODE}")" in
  fail) exit 3;;
  empty) exit 0;;
  blank) echo; echo "host-of-$1"; exit 0;;
  spaces) echo "two words"; exit 0;;
  colon) echo "name:22"; exit 0;;
  dash) echo "-oProxyCommand=x"; exit 0;;
  padded) echo "   host-of-$1   "; exit 0;;
  crlf) printf 'host-of-%s\\r\\nignored\\n' "$1"; exit 0;;
  multi) echo "host-of-$1"; echo "second-line"; exit 0;;
  slow) sleep 0.6; echo "host-of-$1"; exit 0;;
  byrole) if [ "$1" = "slowrole" ]; then sleep 1.5; fi; echo "host-of-$1"; exit 0;;
  hang) echo $$ > "{T}/hang.pid"; exec sleep 60;;
  moved) echo "moved-$1"; exit 0;;
  unicode) echo "hôst"; exit 0;;
  slash) echo "a/b"; exit 0;;
  semi) echo "a;b"; exit 0;;
  at) echo "user@host-1.example.net"; exit 0;;
  big) head -c 5000 /dev/zero | tr '\\0' a; echo; exit 0;;
  flood) echo $$ > "{T}/flood.pid"; exec yes aaaaaaaa;;
  gchild) sleep 60 & echo $! > "{T}/gchild.pid"; wait;;
esac
echo "host-of-$1"
''', encoding="utf-8")
STUB2.write_text('#!/bin/sh\necho "else-$1"\n', encoding="utf-8")
for s_ in (STUB, STUB2): s_.chmod(0o755)

toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^bash_host = "[^"]*"', 'bash_host = "host:primary"', toml); assert n == 1
toml, n = re.subn(r'(?m)^form_machines = \[[^\]]*\]', 'form_machines = ["host:primary", "db-primary"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^ssh_hosts = \[\]', 'ssh_hosts = ["host:spare", "box-d", "host:spare"]', toml); assert n == 1
CONF = T / "stackshot.toml"
BASE_TOML = toml
def write_conf(lookup: str) -> None:
    CONF.write_text(BASE_TOML + f'\n[hosts]\nlookup = "{lookup}"\ntimeout = 5\ncache_seconds = 30\n', encoding="utf-8")
write_conf(f"{STUB} {{role}}")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=str(CONF), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for k in ("STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID"): os.environ.pop(k, None)
for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as C
from stackshot.core import agentbox as AB
from stackshot.fleet import fleet as FL
from stackshot.model import step_commands as SC
from stackshot.service import projects as PS

CLOCK = [1000.0]
C._host_clock = lambda: CLOCK[0]
def calls() -> int: return LOG.read_text().count("--\n") if LOG.exists() else 0
def logged() -> list[list[str]]:
    out, cur = [], []
    for ln in (LOG.read_text().splitlines() if LOG.exists() else []):
        if ln == "--": out.append(cur); cur = []
        else: cur.append(ln)
    return out
def forget():
    """Every answer and failure gone (what a fresh process knows); config._host_reset keeps the last good hosts, which a reload must."""
    C._HOST_GOOD.clear(); C._HOST_FAILED.clear()
def fresh(mode="ok", **hosts):
    """Forget every answer, clear the log, set the stub's mode and the [hosts] table the next checks run under (the stub by default)."""
    forget(); LOG.write_text(""); MODE.write_text(mode); CLOCK[0] += 1000
    C.CFG["hosts"] = {"lookup": f"{STUB} {{role}}", "timeout": 5, "cache_seconds": 30, **hosts}
    if "lookup" in hosts and hosts["lookup"] is None: del C.CFG["hosts"]["lookup"]
def err_of(fn):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf): r = fn()
    return r, buf.getvalue()
def quiet(fn):
    return err_of(fn)[0]

try:
    # ---- plain values are left alone
    fresh()
    plain_list = ["box-a", "box-b"]
    C.CFG["zz"] = {"s": "plain", "n": 7, "f": 1.5, "b": True, "l": plain_list, "t": {"inner": "host:web"}, "e": "", "nested": [["host:web"]], "sp": "host web", "pre": "ahost:web", "u": "host"}
    check("a plain string comes back as it is", C.get("zz", "s") == "plain")
    check("a number, a float and a bool come back as they are", (C.get("zz", "n"), C.get("zz", "f"), C.get("zz", "b")) == (7, 1.5, True))
    check("a list of plain items is the same object, untouched", C.get("zz", "l") is plain_list)
    check("a table is returned as it is, a host word inside it untouched (a reader that takes the table whole resolves its own key)", C.get("zz", "t") is C.CFG["zz"]["t"] and C.get("zz", "t") == {"inner": "host:web"})
    check("a list inside a list is not looked into", C.get("zz", "nested") == [["host:web"]])
    check("'host web', 'ahost:web', 'host' and '' are no host words", [C.get("zz", k) for k in ("sp", "pre", "u", "e")] == ["host web", "ahost:web", "host", ""])
    check("a missing key gives the default, unresolved", C.get("zz", "nope", default="host:web") == "host:web")
    check("none of that ran the lookup", calls() == 0, calls())

    # ---- resolved at the leaf
    C.CFG["zz"]["w"] = "host:web"; C.CFG["zz"]["l2"] = ["box-a", "host:web", "host:db-2", 5, "box-a"]
    check("get() resolves a host word at its leaf", C.get("zz", "w") == "host-of-web", C.get("zz", "w"))
    r = C.get("zz", "l2")
    check("each string item of a list is resolved, the plain ones and the non-strings kept in their places", r == ["box-a", "host-of-web", "host-of-db-2", 5, "box-a"], r)
    check("the list in the config was not rewritten", C.CFG["zz"]["l2"][1] == "host:web")
    check("config.host() resolves one value", C.host("host:web") == "host-of-web")
    check("config.host() returns another value unchanged (a string, a number, a list, None)", (C.host("box-a"), C.host(3), C.host(["host:web"]), C.host(None)) == ("box-a", 3, ["host:web"], None))
    check("a host word with whitespace around it is resolved (a reader strips it too)", C.host("  host:web \n") == "host-of-web")
    check("roles are allowed letters, digits, '-', '_' and '.'", C.host("host:A_b-2.c") == "host-of-A_b-2.c")

    # ---- the cache
    fresh()
    for _ in range(20): C.host("host:web")
    check("20 reads inside cache_seconds make one lookup", calls() == 1, calls())
    CLOCK[0] += 29.9; C.host("host:web")
    check("…still one just before the end of cache_seconds", calls() == 1, calls())
    CLOCK[0] += 0.2; C.host("host:web"); C.host("host:web")
    check("…a second one after it (and only one)", calls() == 2, calls())
    C.host("host:db")
    check("each role is cached on its own", calls() == 3 and logged()[-1] == ["db"], logged())
    fresh(cache_seconds=0)
    C.host("host:web"); C.host("host:web")
    check("cache_seconds = 0 looks up at every read", calls() == 2, calls())
    fresh(cache_seconds="x"); C.host("host:web"); C.host("host:web")
    check("a cache_seconds that is not a number reads as the default 30", calls() == 1, calls())

    # ---- a later failure keeps the last good value; the retry spacing
    fresh()
    check("a good first answer", C.host("host:web") == "host-of-web")
    CLOCK[0] += 31; MODE.write_text("fail")
    got, errtxt = err_of(lambda: C.host("host:web"))
    check("the lookup fails after the cache ran out: the last good host still answers", got == "host-of-web" and calls() == 2, (got, calls()))
    check("…with one line on stderr, naming the role and the reason", errtxt.count("\n") == 1 and "'web'" in errtxt and "exit 3" in errtxt and "last good" in errtxt, errtxt)
    CLOCK[0] += 3
    got, errtxt = err_of(lambda: [C.host("host:web") for _ in range(10)][-1])
    check("inside the 5 seconds after a failure no new lookup is made, the last good value answers", got == "host-of-web" and calls() == 2 and errtxt == "", (got, calls(), errtxt))
    CLOCK[0] += 2.5
    got, errtxt = err_of(lambda: C.host("host:web"))
    check("after the 5 seconds the lookup is tried again, fails again, the last good value still stands, and the streak says nothing more", got == "host-of-web" and calls() == 3 and errtxt == "", (got, calls(), errtxt))
    CLOCK[0] += 5.1; MODE.write_text("moved")
    check("when the lookup works again its new answer replaces the old", C.host("host:web") == "moved-web" and calls() == 4)
    CLOCK[0] += 31; MODE.write_text("fail")
    got, errtxt = err_of(lambda: C.host("host:web"))
    check("a failure after a recovery is a new streak, with its own line", got == "moved-web" and errtxt.count("\n") == 1, (got, errtxt))

    # ---- no good value: the word stays as written
    fresh(lookup=None)
    check("no [hosts] lookup: the word is unchanged and nothing runs", C.host("host:web") == "host:web" and C.get("zz", "w") == "host:web" and calls() == 0)
    C.CFG.pop("hosts", None)
    check("no [hosts] table at all: the same", C.host("host:web") == "host:web" and calls() == 0)
    fresh(lookup="")
    check("an empty lookup: unchanged", C.host("host:web") == "host:web" and calls() == 0)
    fresh(lookup=12)
    check("a lookup that is not a string: unchanged", C.host("host:web") == "host:web" and calls() == 0)
    C.CFG["hosts"] = "not a table"
    check("[hosts] that is not a table: unchanged", C.host("host:web") == "host:web")
    fresh("fail")
    got, errtxt = err_of(lambda: C.host("host:web"))
    check("the first lookup fails: the word is unchanged (not '', not a guess)", got == "host:web" and calls() == 1 and errtxt.count("\n") == 1 and "as written" in errtxt, (got, errtxt))
    CLOCK[0] += 2; check("…and is not tried again within 5 seconds", quiet(lambda: C.host("host:web")) == "host:web" and calls() == 1)
    CLOCK[0] += 4; MODE.write_text("ok")
    check("…but is after them, and then resolves", C.host("host:web") == "host-of-web" and calls() == 2)
    fresh(lookup=f"{T}/no-such-command {{role}}")
    check("a command that is not found: unchanged, no exception", quiet(lambda: C.host("host:web")) == "host:web")
    fresh(lookup=f"{STUB} 'unbalanced {{role}}")
    check("a template with an unbalanced quote: unchanged, no exception", quiet(lambda: C.host("host:web")) == "host:web")
    fresh(lookup=f"{STUB} web")
    check("a lookup with no {role} in it is not run", quiet(lambda: C.host("host:web")) == "host:web" and calls() == 0)
    fresh(lookup="host:loop")
    t0 = time.monotonic()
    check("a lookup that is itself a host word neither recurses nor hangs: the word stays", quiet(lambda: C.host("host:web")) == "host:web" and C.get("hosts", "lookup") == "host:loop" and time.monotonic() - t0 < 3)
    fresh(timeout=0)
    check("a timeout of 0 reads as the default 5", C.host("host:web") == "host-of-web")
    fresh(timeout=-2); check("a negative timeout too", C.host("host:web") == "host-of-web")
    fresh(timeout=True); check("and a bool", C.host("host:web") == "host-of-web")

    # ---- what a lookup may print
    for mode, name, want in (("empty", "no output", "host:web"), ("blank", "an empty first line (the host on a later line does not count)", "host:web"),
                             ("spaces", "a name with a space inside", "host:web"), ("colon", "a name with a colon", "host:web"), ("dash", "a name that starts with '-' (an ssh option)", "host:web"),
                             ("fail", "a non-zero exit", "host:web"),
                             ("unicode", "a name with a character outside letters, digits and . _ @ -", "host:web"), ("slash", "a name with a slash", "host:web"), ("semi", "a name with a semicolon", "host:web"),
                             ("big", "more than 4096 bytes on the first line", "host:web"),
                             ("at", "user@host.example, the form ssh takes (accepted)", "user@host-1.example.net"),
                             ("padded", "a first line with spaces around it (taken stripped)", "host-of-web"), ("crlf", "a first line ended by CR LF", "host-of-web"),
                             ("multi", "more lines after the first (ignored)", "host-of-web")):
        fresh(mode)
        got = quiet(lambda: C.host("host:web"))
        check(f"output: {name}", got == want, got)

    # ---- a lookup that never answers is ended
    fresh("hang", timeout=0.5)
    t0 = time.monotonic(); got, errtxt = err_of(lambda: C.host("host:web")); took = time.monotonic() - t0
    check("a lookup that never answers is a failure within the timeout (bounded time)", got == "host:web" and 0.4 < took < 4, (got, took))
    check("…with its reason on the one stderr line", "no answer in 0.5 s" in errtxt, errtxt)
    pid = (T / "hang.pid").read_text().strip() if (T / "hang.pid").exists() else ""
    check("…and the process it started is gone", pid.isdigit() and not os.path.exists(f"/proc/{pid}"), pid)

    fresh("flood", timeout=5)
    t0 = time.monotonic(); got, errtxt = err_of(lambda: C.host("host:web")); took = time.monotonic() - t0
    check("a lookup that never stops printing is a failure at once (its output is read up to 4096 bytes), not at the timeout", got == "host:web" and took < 3 and "4096 bytes" in errtxt, (got, took, errtxt))
    pid = (T / "flood.pid").read_text().strip() if (T / "flood.pid").exists() else ""
    check("…and the process it started is ended", pid.isdigit() and not os.path.exists(f"/proc/{pid}"), pid)
    fresh("gchild", timeout=0.5)
    t0 = time.monotonic(); got = quiet(lambda: C.host("host:web")); took = time.monotonic() - t0
    gpid = (T / "gchild.pid").read_text().strip() if (T / "gchild.pid").exists() else ""
    gone = False
    for _ in range(40):
        if gpid.isdigit() and not os.path.exists(f"/proc/{gpid}"): gone = True; break
        time.sleep(0.05)
    check("a lookup that left a child holding its output is ended within the timeout, and the child (a grandchild of the server) is ended with it: the whole process group is killed", got == "host:web" and took < 4 and gone, (got, took, gpid, gone))
    if gpid.isdigit() and os.path.exists(f"/proc/{gpid}"):
        try: os.kill(int(gpid), 9)       # by the pid the stub wrote, never by name
        except OSError: pass

    # ---- no shell
    fresh(lookup=f"{STUB} {{role}} ; touch {SENT} && echo x > {SENT} $(touch {SENT}) `touch {SENT}`")
    got = C.host("host:web")
    args = logged()[0] if logged() else []
    check("a template with shell characters runs no shell: the words go to the command as they are, nothing is created", not SENT.exists() and args[:2] == ["web", ";"] and "&&" in args and "$(touch" in args, (args, SENT.exists()))
    check("…and the command's first line still answers", got == "host-of-web", got)
    fresh(lookup=f"{STUB} pre-{{role}}-post")
    C.host("host:web")
    check("{role} is replaced inside a longer word", logged() == [["pre-web-post"]], logged())
    fresh(lookup=f"{STUB} --role={{role}} {{role}}")
    C.host("host:web")
    check("{role} is replaced in every word it stands in", logged() == [["--role=web", "web"]], logged())
    os.environ["HOME"] = tmp
    (T / "bin").mkdir(exist_ok=True); (T / "bin" / "where-is").write_bytes(STUB.read_bytes()); (T / "bin" / "where-is").chmod(0o755)
    fresh(lookup="~/bin/where-is {role}")
    got = C.host("host:web")
    check("a leading ~ is expanded in each word", got == "host-of-web", got)
    for bad in ("host:a b", "host:a:b", "host:", "host:-x", "host:a;touch", f"host:a;touch {SENT}", "host:$(id)", "host:`id`", "host:a|b", "host:a/b", "host:a&b", "host:a\nb", "host: a", "host:é", "HOST:a", "host:a'b", "host:a\"b", "host:a>b"):
        fresh()
        got = C.host(bad)
        check(f"a bad role {bad!r} is no host word: left as written, nothing runs", got == bad and calls() == 0, (got, calls()))
    check("…and no file was created by any of them", not SENT.exists())

    # ---- threads
    fresh("slow")
    out, ths = [], []
    gate = threading.Barrier(8)
    def ask():
        gate.wait(); out.append(C.host("host:web"))
    for _ in range(8): ths.append(threading.Thread(target=ask))
    for t in ths: t.start()
    for t in ths: t.join(20)
    check("eight threads asking one role at once cause one lookup, and all get its answer", calls() == 1 and out == ["host-of-web"] * 8, (calls(), out))
    fresh("byrole")
    res = {}
    def slow_role(): res["slow"] = C.host("host:slowrole")
    t = threading.Thread(target=slow_role); t.start(); time.sleep(0.4)
    t0 = time.monotonic(); fast = C.host("host:quick"); fast_took = time.monotonic() - t0
    t.join(20)
    check("a slow lookup of one role does not hold up another role", fast == "host-of-quick" and fast_took < 1.0 and res.get("slow") == "host-of-slowrole", (fast, fast_took, res))
    fresh("slow")
    out2 = []
    t = threading.Thread(target=lambda: out2.append(C.host("host:web"))); t.start(); time.sleep(0.2)
    t0 = time.monotonic(); during = C.get("zz", "s"); plain_took = time.monotonic() - t0
    t.join(20)
    check("a plain read is not held up by a lookup in progress", during == "plain" and plain_took < 0.3 and out2 == ["host-of-web"], (during, plain_took, out2))
    fresh("fail")
    out3 = []; gate = threading.Barrier(6)
    def ask3():
        gate.wait(); out3.append(quiet(lambda: C.host("host:web")))
    ths = [threading.Thread(target=ask3) for _ in range(6)]
    for t in ths: t.start()
    for t in ths: t.join(20)
    check("six threads asking a role whose lookup fails cause one lookup, and all see the word", calls() == 1 and out3 == ["host:web"] * 6, (calls(), out3))

    # ---- the four readers
    fresh(); C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": ["host:primary", "db-primary"]}
    check("form_machines (the form gate's helper) resolves each item and keeps the plain ones", PS._cfg_names("form_machines", []) == ["host-of-primary", "db-primary"], PS._cfg_names("form_machines", []))
    check("…a caller token of the machine the role names is the form's, one of another is not", PS._form_call("host-of-primary", "form-x") and PS._form_call("db-primary", "form-x") and not PS._form_call("host-b", "form-x"))
    C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": "host:primary"}
    check("…a bare string counts as one item, resolved", PS._cfg_names("form_machines", []) == ["host-of-primary"])
    check("…the default of an unset key is returned as it is", PS._cfg_names("other", ["host-z"]) == ["host-z"])
    bg_sec = {"bg_senders": ["bg-x"], "bg_machines": ["host:primary", "db-primary"], "form_machines": ["db-form"]}
    C.CFG["project_agent"] = dict(bg_sec)
    okc, no = PS._bg_call("host-of-primary", "bg-x", False, ""), PS._bg_call("host-other", "bg-x", False, "")
    check("bg_machines: a host word in it is resolved; a background call from the machine it names is allowed, from another a 403", okc == (True, None) and no[0] is False and no[1] is not None and no[1][0] == 403, (okc, no))
    check("…a plain item of it still matches, and form_machines is not consulted while bg_machines is set", PS._bg_call("db-primary", "bg-x", False, "") == (True, None) and PS._bg_call("db-form", "bg-x", False, "")[0] is False)
    C.CFG["project_agent"] = {"bg_senders": ["bg-x"], "bg_machines": [], "form_machines": ["host:primary", "db-form"]}
    check("an empty bg_machines falls back to form_machines, its host words resolved too", PS._bg_call("host-of-primary", "bg-x", False, "") == (True, None) and PS._bg_call("db-form", "bg-x", False, "") == (True, None) and PS._bg_call("host-other", "bg-x", False, "")[0] is False)
    C.CFG["project_agent"] = {"bg_senders": ["bg-x"], "form_machines": "host:primary"}
    check("…an absent bg_machines the same", PS._bg_call("host-of-primary", "bg-x", False, "") == (True, None))
    fresh(lookup=None); C.CFG["project_agent"] = dict(bg_sec)
    check("…with no lookup the word stays as written and matches no machine's token", PS._bg_call("host-of-primary", "bg-x", False, "")[0] is False and PS._bg_call("host:primary", "bg-x", False, "") == (True, None))
    fresh(lookup=None); C.CFG["project_agent"] = {"form_senders": ["form-x"], "form_machines": ["host:primary", "db-primary"]}
    check("…with no lookup the word stays in the list and matches no machine's token", PS._cfg_names("form_machines", []) == ["host:primary", "db-primary"] and not PS._form_call("host-of-primary", "form-x"))
    fresh(); C.CFG["steps"] = {"owner_shell": "powershell", "bash_host": "host:primary"}
    check("steps.bash_host resolves", SC.bash_host() == "host-of-primary", SC.bash_host())
    C.CFG["steps"]["bash_host"] = " host:primary "
    check("…also with spaces around the word, and the fix text names the resolved host", SC.bash_host() == "host-of-primary" and "host-of-primary" in SC.bash_fix(), SC.bash_fix())
    fresh(lookup=None); C.CFG["steps"] = {"owner_shell": "powershell", "bash_host": "host:primary"}
    check("…with no lookup it reads as the word, never ''", SC.bash_host() == "host:primary")
    fresh(); C.CFG["agents_box"] = {"ssh": "host:agents"}
    check("agents_box.ssh resolves", AB.host() == "host-of-agents" and AB.enabled() is True, AB.host())
    fresh(lookup=f"{STUB2} {{role}}"); C.CFG["agents_box"] = {"ssh": "host:agents"}
    check("…another lookup command, another answer", AB.host() == "else-agents", AB.host())
    me = socket.gethostname()
    fake_me = T / "where-me"; fake_me.write_text(f'#!/bin/sh\necho "{me}"\n'); fake_me.chmod(0o755)
    fresh(lookup=f"{fake_me} {{role}}"); C.CFG["agents_box"] = {"ssh": "host:agents"}
    check("…a role that moved to this very machine reads as one box (local), as its name always did", AB.host() == "" and AB.enabled() is False, AB.host())
    fresh(lookup=None); C.CFG["agents_box"] = {"ssh": "host:agents"}
    check("…with no lookup it stays as written: ssh to it fails visibly, it is never read as local", AB.host() == "host:agents" and AB.enabled() is True)
    fresh(); C.CFG["machines_panel"] = {"ssh_hosts": ["host:spare", "box-d", "host:spare"]}
    check("machines_panel.ssh_hosts resolves item by item (a repeat once)", FL.ssh_host_names() == ["host-of-spare", "box-d"], FL.ssh_host_names())
    check("…and the panel's order lists the resolved name", "host-of-spare" in FL.machines_order({"a": "box-a"}, FL.ssh_host_names()))
    C.CFG["machines_panel"] = {"ssh_hosts": "host:spare"}
    check("…a bare string is one host, resolved", FL.ssh_host_names() == ["host-of-spare"])
    fresh(lookup=None); C.CFG["machines_panel"] = {"ssh_hosts": ["host:spare", "box-d"]}
    check("…with no lookup the word is listed as written (an unreachable card, never a missing one)", FL.ssh_host_names() == ["host:spare", "box-d"])

    # ---- the colors routes look a host word up off the event loop
    import asyncio
    from stackshot.web.routes import ui_api as UI
    fresh(cache_seconds=0); C.CFG["project_agent"] = {"form_senders": ["sala-web"], "form_machines": ["host:primary"]}      # cache_seconds 0: every read of the word runs a lookup, so each gate shows its thread
    seen = []; real_lookup = C._host_lookup
    def spy(*a, **k):
        seen.append(threading.get_ident()); return real_lookup(*a, **k)
    C._host_lookup = spy
    class Req:
        headers = {"authorization": "Bearer x"}
        async def json(self): return {"sender": "sala-web", "name": "n", "values": {}}
    UI._client_machine = lambda auth, request=None: "host-of-primary"
    UI._colors_body = lambda request: asyncio.sleep(0, {"sender": "sala-web"})
    UI._colors_run = lambda op, body, via: (op, via)
    loop_ids = []
    async def drive():
        loop_ids.append(threading.get_ident())
        r1 = await UI._colors_machine(Req(), "list")
        forget(); CLOCK[0] += 1000
        r2 = await UI._colors_machine(Req(), "save")
        return r1, r2
    r1, r2 = asyncio.run(drive())
    UI._client_machine = lambda auth, request=None: "host-other"
    r3 = asyncio.run(UI._colors_machine(Req(), "list"))
    C._host_lookup = real_lookup
    check("a colors call from the machine a role names passes the gate (list, and save with the form's sender)", getattr(r1, "status_code", 200) == 200 and getattr(r2, "status_code", 200) == 200, (r1, r2))
    check("…and a machine the role does not name is a 403", getattr(r3, "status_code", None) == 403, r3)
    check("the host-word lookup of the colors routes ran, and on a worker thread, never on the event loop's", len(seen) >= 4 and loop_ids[0] not in seen, (seen, loop_ids))

    # ---- reload and the command line
    C.reload(); forget(); LOG.write_text(""); MODE.write_text("ok"); CLOCK[0] += 1000
    check("after a reload the config is the file's", C.get("machines_panel", "ssh_hosts") == ["host-of-spare", "box-d", "host-of-spare"] and calls() == 1, (C.get("machines_panel", "ssh_hosts"), calls()))
    CLOCK[0] += 1; C.host("host:spare")
    check("an answer is cached", calls() == 1)
    write_conf(f"{STUB2} {{role}}")
    changed = quiet(C.reload)
    check("a reload of a changed file went through", changed is not None and "hosts.lookup" in changed, changed)
    check("…it made the answers due: the new lookup answers at once, inside cache_seconds", C.host("host:spare") == "else-spare", C.host("host:spare"))
    MODE.write_text("fail"); write_conf(f"{STUB} {{role}}"); quiet(C.reload); CLOCK[0] += 1
    calls_before = calls()
    got = quiet(lambda: C.host("host:spare"))
    check("…a reload makes the answers due, not gone: the next read runs the lookup again, and when it fails the last good host of that same command still answers", calls() == calls_before + 1 and got == "host-of-spare", (got, calls(), calls_before))
    write_conf(f"{STUB2.parent}/where-none {{role}}"); quiet(C.reload); CLOCK[0] += 1
    check("…while a changed lookup command has no answer of its own: another command's last good host is not used, the word stays", quiet(lambda: C.host("host:spare")) == "host:spare")
    MODE.write_text("ok"); write_conf(f"{STUB} {{role}}")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["STACKSHOT_CONFIG"] = str(CONF)
    r = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "get", "steps.bash_host"], capture_output=True, text=True, env=env, timeout=60, cwd=tmp)
    check("`config.py get steps.bash_host` prints the host the word names", r.returncode == 0 and r.stdout.strip() == "host-of-primary", (r.returncode, r.stdout, r.stderr[-300:]))
    r = subprocess.run([sys.executable, "-I", f"{STACK}/stackshot/core/config.py", "get", "machines_panel.ssh_hosts"], capture_output=True, text=True, env=env, timeout=60, cwd=tmp)
    check("…a list is printed with its words resolved", r.returncode == 0 and json.loads(r.stdout) == ["host-of-spare", "box-d", "host-of-spare"], (r.returncode, r.stdout, r.stderr[-300:]))
finally:
    if HOME_WAS is None: os.environ.pop("HOME", None)
    else: os.environ["HOME"] = HOME_WAS
    _scratch.cleanup()

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
