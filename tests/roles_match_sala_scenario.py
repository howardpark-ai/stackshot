"""Scenario test: the roles list matches what sala runs.

  2  the name-line session of a finished page (status among the retired ones) is marked retired, as is one of a page with user-facing agents; an active page's
     one session is not;
  3  a name line held by several pages is placed on an active page: a page whose status retires it never outranks an active one, however shallow its key; among
     pages that are all finished one is still chosen;
  4  every roles entry carries `live`: whether `sala sessions --json` lists the name; the field is left out (not false) when sala cannot be read (no store, bad exit,
     bad output, a slow read, no executable); sala is read once per build; every other key and entry stays; the roles.json the server writes carries it, and a
     change in who is listed rewrites the file; readers that take extra keys (the hub repo's) still find role and project.

A fake `sala` script stands in for the real one (STACKSHOT_SALA); fixture pages, no network.    tests/run-suite roles_match_sala        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, stat, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="rolessala-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "links", "state/anchor-hub", "brain/projects", "brain/infra", "bin"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

# the fake sala: mode and listed names come from files beside it; each run is counted
FAKE = T / "bin/sala"
FAKE.write_text(f"""#!/usr/bin/env python3
import json, sys, time
d = {str(T / "bin")!r}
open(d + "/calls", "a").write(" ".join(sys.argv[1:]) + "\\n")
mode = open(d + "/mode").read().strip()
if mode == "slow": time.sleep(3)
if mode == "fail": sys.exit(3)
if mode == "garbage": print("not json"); sys.exit(0)
if mode == "nolist": print(json.dumps({{"schema": 1}})); sys.exit(0)
if mode == "child":
    import subprocess
    c = subprocess.Popen(["sleep", "30"], stdout=sys.stdout)
    open(d + "/child.pid", "w").write(str(c.pid))
    time.sleep(30)
names = json.load(open(d + "/names.json"))
al = json.load(open(d + "/aliases.json"))
print(json.dumps({{"schema": 1, "sessions": [{{"id": "id-" + n, "name": n, "state": ("idle" if i % 2 else "live"), "aliases": al.get(n, [])}} for i, n in enumerate(names)]}}))
""", encoding="utf-8")
FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR)
def sala(mode="ok", names=(), aliases=None):
    (T / "bin/mode").write_text(mode); (T / "bin/names.json").write_text(json.dumps(list(names))); (T / "bin/aliases.json").write_text(json.dumps(aliases or {}))
def calls():
    f = T / "bin/calls"; return len(f.read_text().splitlines()) if f.exists() else 0
os.environ["STACKSHOT_SALA"] = str(FAKE)
sala("ok", [])

def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
# a finished page and an active one-session page; a page with a front agent; a name held by several pages
page("projects/fin.md", "type: project\ntitle: Fin\ndisplay-name: home-fin\nstatus: done")
page("projects/act.md", "type: project\ntitle: Act\ndisplay-name: home-act\nstatus: active")
page("projects/served.md", "type: project\ntitle: Served\ndisplay-name: home-served\nagents:\n  home-served-main: talks\n  background:\n    home-served-bg: builds\nstatus: active")
page("projects/multi-old.md", "type: project\ntitle: Multi old\ndisplay-name: home-multi\nstatus: completed")
page("ops/multi-new.md", "type: note\ntitle: Multi new\ndisplay-name: home-multi\nhub: projects/act\nstatus: active")
page("projects/multi-note/sub.md", "type: project\ntitle: Multi sub\ndisplay-name: home-multi\nstatus: archived")
page("projects/gone-a.md", "type: project\ntitle: Gone a\ndisplay-name: home-gone\nstatus: retired")
page("ops/gone-b/deep.md", "type: note\ntitle: Gone b\ndisplay-name: home-gone\nstatus: closed")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
from stackshot.projects import pages as p
from stackshot.anchors import anchors as A
from stackshot.fleet import clients as C
from stackshot.web import server
from stackshot.projects import project_registry as _projects_registry
p.cmd_registry(quiet=True); R = json.loads((T / "store/projects.json").read_text())["pages"]
check("(setup) the fixture registry lists the pages and their statuses", R["projects/fin"].get("status") == "done" and R["ops/multi-new"].get("hub") == "projects/act", {k: (v.get("status"), v.get("session")) for k, v in R.items()})

# ---- 2. a finished page's name line is retired
RL = A.session_roles(R)
check("2: the name line of a finished page is marked retired (role stays the name-line role, project stays the page)", RL.get("home-fin") == {"role": "keeper", "project": "projects/fin", "retired": True}, RL.get("home-fin"))
check("2: …a page with a front agent still retires its name line", RL.get("home-served") == {"role": "keeper", "project": "projects/served", "retired": True}, RL.get("home-served"))
check("2: …an active one-session page's name line is not retired (session_roles, and file_roles makes it front)", RL.get("home-act") == {"role": "keeper", "project": "projects/act"}
      and A.file_roles(R).get("home-act") == {"role": "front", "project": "projects/act"}, (RL.get("home-act"), A.file_roles(R).get("home-act")))
check("2: …a finished page's name line stays a keeper entry in file_roles (never front)", A.file_roles(R).get("home-fin") == {"role": "keeper", "project": "projects/fin", "retired": True}, A.file_roles(R).get("home-fin"))
check("2: …agents are unchanged: a front and a background agent of the served page", RL.get("home-served-main") == {"role": "front", "project": "projects/served"} and RL.get("home-served-bg") == {"role": "back", "project": "projects/served"},
      (RL.get("home-served-main"), RL.get("home-served-bg")))

# ---- 3. the project of a name held by several pages
check("3: a name line on a finished page, a finished sub-page and an active page is placed on the active one (it is not retired)", RL.get("home-multi") == {"role": "keeper", "project": "ops/multi-new"}, RL.get("home-multi"))
check("3: …a finished page never outranks an active one, even when it has the shallower key and no hub (the active page has a hub line)", R["projects/multi-old"].get("status") == "completed" and "hub" not in R["projects/multi-old"]
      and RL["home-multi"]["project"] != "projects/multi-old", RL.get("home-multi"))
check("3: …a name held only by finished pages still gets one project (the shallower key) and is retired", RL.get("home-gone") == {"role": "keeper", "project": "projects/gone-a", "retired": True}, RL.get("home-gone"))
R2 = {k: dict(v) for k, v in R.items()}; R2["projects/multi-old"]["status"] = "active"
check("3: …two active pages: the usual ranking (no hub, shallower key) still decides", A.session_roles(R2).get("home-multi", {}).get("project") == "projects/multi-old", A.session_roles(R2).get("home-multi"))
R3 = {k: dict(v) for k, v in R.items()}; R3["projects/multi-old"] = dict(R3["projects/multi-old"], agents={"home-multi": "front"})
check("3: …a front agent listed on a finished page still outranks a name line on an active one (the role order is unchanged)", A.session_roles(R3).get("home-multi", {}).get("role") == "front"
      and A.session_roles(R3)["home-multi"]["project"] == "projects/multi-old", A.session_roles(R3).get("home-multi"))

# ---- 4. the live flag
check("4: no `live` field when no live set is given (existing callers)", all("live" not in e for e in RL.values()) and all("live" not in e for e in A.file_roles(R).values()))
LV = {"home-act", "home-served-main", "home-other-session"}
RLL = A.session_roles(R, LV); FRL = A.file_roles(R, LV)
check("4: with a live set every entry carries live true/false by whether the set lists its name", all(isinstance(e.get("live"), bool) for e in RLL.values()) and {n for n, e in RLL.items() if e["live"]} == {"home-act", "home-served-main"},
      {n: e["live"] for n, e in RLL.items()})
check("4: …the same in file_roles, whose front upgrade still applies", FRL["home-act"] == {"role": "front", "project": "projects/act", "live": True} and FRL["home-fin"]["live"] is False, (FRL.get("home-act"), FRL.get("home-fin")))
check("4: …nothing else changes: every entry minus live equals the entry without a live set, and no entry is added or dropped",
      set(RLL) == set(RL) and {n: {k: v for k, v in e.items() if k != "live"} for n, e in RLL.items()} == RL and {n: {k: v for k, v in e.items() if k != "live"} for n, e in FRL.items()} == A.file_roles(R))
check("4: …an empty live set (sala lists nobody) reads false for everyone, not omitted", all(e["live"] is False for e in A.session_roles(R, set()).values()))

# sala_live: gated on the fleet store; reads the fake sala
check("4: sala_live reads nothing when no fleet store is configured ([client] session_links empty): None, sala not run", A.sala_live() is None and calls() == 0, calls())
C._links_dir = lambda: T / "links"               # a configured store: the reader may run sala
sala("ok", ["home-act", "home-served-main", "home-idle"])
check("4: sala_live → the set of names `sala sessions --json` lists (any state), one run, with the args sessions --json", A.sala_live() == {"home-act", "home-served-main", "home-idle"} and calls() == 1
      and (T / "bin/calls").read_text().strip() == "sessions --json", ((T / "bin/calls").read_text(), calls()))
for mode in ("fail", "garbage", "nolist"):
    sala(mode, ["home-act"])
    check(f"4: sala_live → None when sala answers badly ({mode})", A.sala_live() is None)
sala("slow", ["home-act"]); t0 = time.time()
check("4: sala_live → None when the read is slower than the timeout, and returns at the timeout", A.sala_live(timeout=0.5) is None and time.time() - t0 < 2.5, time.time() - t0)
# aliases: a roles key that is an alias of a live session reads live
sala("ok", ["home-act", "home-served-main"], {"home-act": ["home-act-old", "home-act-older"], "home-served-main": []})
check("4: sala_live → each session's name and every alias of it", A.sala_live() == {"home-act", "home-act-old", "home-act-older", "home-served-main"}, A.sala_live())
AL = A.session_roles(R, A.sala_live())
check("4: an entry named by an alias of a live session reads live: true; a name sala knows neither way reads false", AL["home-act"]["live"] is True and AL["home-fin"]["live"] is False, (AL["home-act"], AL["home-fin"]))
sala("ok", ["home-live-name"], {"home-live-name": ["home-act"]})
check("4: …a roles key that is only an alias (sala lists the session under a newer name) reads live: true", A.session_roles(R, A.sala_live())["home-act"]["live"] is True)
sala("ok", ["home-live-name"], {"home-live-name": ["home-fin"]})
# a child holding the output pipe: the timeout kills sala's whole process group and returns at the timeout
sala("child", ["home-act"]); t0 = time.time(); cp = T / "bin/child.pid"
try:
    got = A.sala_live(timeout=0.5); took = time.time() - t0
    time.sleep(0.3)
    pid = int(cp.read_text()) if cp.exists() else 0
    alive = False
    if pid:
        try: os.kill(pid, 0); alive = not (pathlib.Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] == "Z")
        except OSError: alive = False
    check("4: sala_live → None at the timeout when sala started a child that keeps the output open, and the child is killed with it", got is None and took < 2.5 and pid > 0 and not alive, (got, took, pid, alive))
finally:
    try:
        pid = int(cp.read_text())
        if os.readlink(f"/proc/{pid}/exe").endswith("/sleep"): os.kill(pid, 9)      # only the fake's own sleep child
    except (OSError, ValueError): pass
sala("ok", ["home-act"]); os.environ["STACKSHOT_SALA"] = str(T / "bin/no-such-sala")
check("4: sala_live → None when there is no executable (never raises)", A.sala_live() is None)
os.environ["STACKSHOT_SALA"] = str(FAKE)

# the server's roles.json: live on every entry, sala read once per build, a change in who is listed rewrites it
RJ = T / "state/roles.json"; t1 = time.time()
sala("ok", ["home-act", "home-served-main"]); c0 = calls()
check("roles.json: written, with live on every entry; sala was read exactly once for the build", _projects_registry._roles_sync(now=t1) is True and calls() == c0 + 1, (calls() - c0))
j = json.loads(RJ.read_text()); S = j["sessions"]
check("roles.json: …each entry holds role, project and live; the live ones are the names sala lists", all({"role", "project", "live"} <= set(e) for e in S.values()) and {n for n, e in S.items() if e["live"]} == {"home-act", "home-served-main"},
      {n: e for n, e in S.items()})
check("roles.json: …entries minus live are what file_roles gives (nothing dropped); the finished page's keeper is retired", {n: {k: v for k, v in e.items() if k != "live"} for n, e in S.items()} == A.file_roles(R) and S["home-fin"].get("retired") is True,
      S.get("home-fin"))
check("roles.json: …unchanged and fresh → not rewritten", _projects_registry._roles_sync(now=t1 + 60) is False)
sala("ok", ["home-act", "home-served-main", "home-served-bg"])
check("roles.json: …a session starting in sala rewrites it (live flips)", _projects_registry._roles_sync(now=t1 + 80) is True and json.loads(RJ.read_text())["sessions"]["home-served-bg"]["live"] is True)
sala("fail", [])
check("roles.json: …sala unreadable → the file is rewritten without the field on any entry (not false for everyone), every other key kept", _projects_registry._roles_sync(now=t1 + 100) is True
      and all("live" not in e for e in json.loads(RJ.read_text())["sessions"].values()) and set(json.loads(RJ.read_text())["sessions"]) == set(S), json.loads(RJ.read_text())["sessions"].get("home-act"))

# the readers in the hub repo take an entry by .get("role"), .get("project"), .get("retired"); an extra key changes none of them
S = json.loads((sala("ok", ["home-act"]), _projects_registry._roles_sync(now=t1 + 120), RJ.read_text())[2])["sessions"]
check("readers: an entry with `live` still has role, project and (where it applies) retired as strings/booleans of the same shape",
      all(isinstance(e["role"], str) and isinstance(e["project"], str) and set(e) <= {"role", "project", "retired", "page_owed", "live"} for e in S.values()), S)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
