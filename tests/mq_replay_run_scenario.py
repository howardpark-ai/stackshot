"""Scenario test for tools/mq_replay.py `run`, `report` and `clean` (tools/mq_replay_run.py): the driver that replays the merge queue's cases on practice branches.

No real GitHub, no network, no real queue. A local bare repository is the "origin" (a pre-receive hook logs every ref that anything creates, moves or deletes there); `salamander`, `gh`,
`systemctl` and `systemd-run` are fakes on PATH. The fake `salamander mq` reads the case's replay file and host file like the real one (add, wait, drop, status, and a driver process that
builds the chain in a clone (an entry per PR, each on the one ahead), pushes the entries' branches, "runs CI" as a function of the pushed tree: a file named BAD_* fails the entry, drops that PR alone, rebuilds the entries behind it on the one ahead, and deletes its branches), answers the
exit codes of `mq wait` (3 tested, 4 tested without CI, 1 ejected or failed, 2 gave up), and refuses to run if the tool had given it the real state folder.

Covers: the replay file (practice base and group prefix, the owner filled from the repository, an explicit owner kept, ci per profile, mode shadow, the case's own XDG folders, the
CI-run poller's folder linked); matches, a forced mismatch (CI fails a PR the old path merged; a wrong recorded tree; a refusal the queue accepts), a conflict ejection with the files, a check
refusal, the on_conflict mend with the tree equal to M's, a group of PRs, a failing PR dropped alone (its mate passing) and the same pair in the build profile; the report table; isolation (a decoy
mergequeue folder byte-identical, main and the PR refs unchanged, every ref anything touched on origin is practice/ or queue/practice/); the idle gate (its three signals, a release going at the start,
a release appearing mid-run: the case is interrupted, its CI cancelled, its PRs dropped, nothing left, exit 75, and `--resume` runs only the cases not done); cleanup after a normal run, after a
case that fails in the middle, after a driver that leaves its branches, after SIGTERM (a driver that will not leave is stopped); --keep; the ref guard (no ref outside practice/ is ever pushed or deleted,
all or nothing); `clean` by run and by age (decoys with similar names survive); --detach; an owner that cannot be derived; and the 20 real cases' replay files and verdict rules.

    tests/run-suite mq_replay_run        → exit 0 / 1"""
import hashlib, importlib.util, json, os, pathlib, re, shutil, signal, subprocess, sys, time
import _scratch
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
TOOL = os.path.join(STACK, "tools", "mq_replay.py")
MOD = os.path.join(STACK, "tools", "mq_replay_run.py")
CASES_REAL = os.path.join(SCR, "mq_replay", "cases.json")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))

ROOT = pathlib.Path(_scratch.mkdtemp(prefix="k2-mqrun-"))
HOME = ROOT / "home"; HOME.mkdir()
BIN = ROOT / "bin"; BIN.mkdir()
FAKE = ROOT / "fake"; FAKE.mkdir(); (FAKE / "units").mkdir()
OUTER_STATE = ROOT / "state"; OUTER_STATE.mkdir()
OUTER_CONF = ROOT / "config"; OUTER_CONF.mkdir()
LOGS = ROOT / "relstate" / "releases"; LOGS.mkdir(parents=True)                                # release.sh's folder: <paths.state>/releases, found through the instance config
INSTANCE_CONFIG = ROOT / "stackshot.toml"; INSTANCE_CONFIG.write_text(f'[paths]\nstate = "{ROOT / "relstate"}"\n')
(OUTER_CONF / "gh").mkdir(); (OUTER_CONF / "gh" / "hosts.yml").write_text("github.com:\n    user: test-user\n    oauth_token: not-a-real-token\n")      # the login lives in a file, as on the real box
(OUTER_CONF / "gh" / "config.yml").write_text("version: 1\n")
TMPD = ROOT / "tmp"; TMPD.mkdir()
(FAKE / "outer_state").write_text(str(OUTER_STATE))
REAL_GIT = shutil.which("git")
SLUG = "acme-org/stackshot"
BASE_ENV = {"HOME": str(HOME), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "TMPDIR": str(TMPD),
            "FAKE_DIR": str(FAKE), "XDG_STATE_HOME": str(OUTER_STATE), "XDG_CONFIG_HOME": str(OUTER_CONF), "STACKSHOT_CONFIG": str(INSTANCE_CONFIG)}
ENV = {**BASE_ENV, "PATH": f"{BIN}:{os.environ['PATH']}"}
AUTHOR = ["-c", "user.name=Test Author", "-c", "user.email=author@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

def g(cwd, *args, ok=True):
    r = subprocess.run([REAL_GIT, "-C", str(cwd), *AUTHOR, *args], capture_output=True, text=True, env={**BASE_ENV, "PATH": os.environ["PATH"]}, timeout=60)
    if ok and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} in {cwd}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()

# ---------------------------------------------------------------- the fakes
FAKE_SAL = r'''#!%PY%
import fcntl, json, os, subprocess, sys, time, tomllib
FAKE = os.environ["FAKE_DIR"]
argv = sys.argv[1:]
def jlog(**kw):
    with open(FAKE + "/calls.log", "a") as f: f.write(json.dumps(kw) + "\n")
def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
if len(argv) < 2 or argv[0] != "mq": sys.exit(9)
sub, repo = argv[1], opt("--repo")
slug = repo.replace("/", "__")
xs, xc = os.environ.get("XDG_STATE_HOME", ""), os.environ.get("XDG_CONFIG_HOME", "")
state = os.path.join(xs, "mergequeue", slug)
cfg = os.path.join(xc, "mergequeue", slug + ".toml")
host = tomllib.load(open(cfg, "rb")) if os.path.exists(cfg) else None
def positional():
    out, skip = [], False
    for a in argv[2:]:
        if skip: skip = False; continue
        if a in ("--repo", "--timeout"): skip = True; continue
        if not a.startswith("--"): out.append(a)
    return out
def load_q():
    try: return json.load(open(state + "/queue.json"))
    except OSError: return {"entries": []}
def update_q(fn):
    os.makedirs(state, exist_ok=True)
    fd = os.open(state + "/queue.lock", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        q = load_q(); res = fn(q)
        tmp = state + "/queue.json.%d.tmp" % os.getpid()
        json.dump(q, open(tmp, "w")); os.replace(tmp, state + "/queue.json")
        return res
    finally: os.close(fd)
def save_group(gr):
    os.makedirs(state + "/groups", exist_ok=True)
    tmp = state + "/groups/%s.tmp" % gr["id"]
    json.dump(gr, open(tmp, "w")); os.replace(tmp, state + "/groups/%s.json" % gr["id"])

if sub == "status":
    if host is None or "replay" not in host:             # the real queue: its state is a file the test controls, nothing here touches a state folder
        jlog(ev="real_status", xdg_state=xs)
        if os.path.exists(FAKE + "/real_status_fail"): print("boom", file=sys.stderr); sys.exit(1)
        p = FAKE + "/real_status.json"
        print(open(p).read() if os.path.exists(p) else '{"groups": []}'); sys.exit(0)
    print(json.dumps({"groups": [], "queue": load_q()["entries"], "replay": host["replay"]})); sys.exit(0)

if host is None or "replay" not in host:
    print("salamander mq: mode off (no replay file in the host config)", file=sys.stderr); sys.exit(1)
rp = json.load(open(host["replay"]))
case, run = rp["case"], rp["run"]
unit = "mq-%s-%s-%s.service" % (slug, run, case)

if sub == "add":
    if not rp["rules"]["base"].startswith("practice/") or not rp["rules"]["queue_prefix"].startswith("queue/practice/"):
        print("the queue is blocked: replay base outside practice/", file=sys.stderr); sys.exit(1)
    if os.path.realpath(xs) == os.path.realpath(open(FAKE + "/outer_state").read().strip()):
        jlog(ev="WROTE_REAL_STATE"); print("the tool gave the real state folder", file=sys.stderr); sys.exit(9)
    if os.path.exists(FAKE + "/fail-" + case):
        print("salamander mq add: simulated failure", file=sys.stderr); sys.exit(1)
    prs = [int(x) for x in positional()]
    update_q(lambda q: q["entries"].extend({"pr": n, "state": "waiting", "reason": "", "group": None, "added": int(time.time()), "ended": None} for n in prs))
    jlog(ev="add", case=case, run=run, prs=prs, ci=rp["ci"], poller_link=os.path.islink(xs + "/salamander"), host=open(cfg).read(), replay=rp, xdg_state=xs, xdg_config=xc)
    p = subprocess.Popen([sys.executable, __file__, "mq", "drive", "--repo", repo], env=os.environ.copy(), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(FAKE + "/units/" + unit + ".pid", "w").write(str(p.pid))
    print("driver started (%s)" % unit); sys.exit(0)

if sub == "drop":
    n = int(positional()[0])
    def drop(q):
        for e in reversed(q["entries"]):
            if e["pr"] == n and e["state"] in ("waiting", "grouped"):
                e.update(state="dropped", reason="dropped", ended=int(time.time())); return True
        return False
    ok = update_q(drop); jlog(ev="drop", case=case, pr=n, ok=ok); sys.exit(0 if ok else 1)

if sub == "wait":
    open(FAKE + "/wait-%s.pid" % case, "w").write(str(os.getpid()))
    n = int(positional()[0]); t = float(opt("--timeout", "0")); end = time.time() + t if t else None
    while True:
        e = next((x for x in reversed(load_q()["entries"]) if x["pr"] == n), None)
        if e is None: print("PR %d is not in the line" % n, file=sys.stderr); sys.exit(2)
        if e["state"] == "tested" and e.get("ci") == "skipped":
            print("PR %d tested (CI not run) (replay ci = skip: built, nothing pushed or tested) [%s]" % (n, e["group"])); sys.exit(4)
        if e["state"] == "tested": print("PR %d tested: %s [%s]" % (n, e["reason"], e["group"])); sys.exit(3)
        if e["state"] in ("failed", "ejected", "dropped", "merged"):
            line = "PR %d %s: %s%s" % (n, e["state"], e["reason"], " [%s]" % e["group"] if e.get("group") else "")
            print(line); print(line, file=sys.stderr); sys.exit(0 if e["state"] == "merged" else 1)
        if end and time.time() >= end: print("PR %d: gave up waiting" % n, file=sys.stderr); sys.exit(2)
        time.sleep(0.05)

if sub != "drive": sys.exit(9)

# ---- the fake driver: builds the chain in a clone of the remote, pushes each entry, "tests" it, drops a failing PR alone and rebuilds the ones behind it, cleans up
clone, remote, rules = host["clone"], host["remote"], rp["rules"]
base, prefix = rules["base"], rules["queue_prefix"]
ident = ["-c", "user.name=Fake", "-c", "user.email=fake@example.invalid", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
def git(*a, check=True):
    r = subprocess.run(["git", *ident, *a], cwd=clone, capture_output=True, text=True)
    if check and r.returncode: raise SystemExit("git %s: %s" % (" ".join(a), r.stderr))
    return r
subprocess.run(["git", "clone", "-q", remote, clone], check=True, capture_output=True)
pushed, counter, hard = [], [0], time.time() + 90
def stubborn(): return os.path.exists(FAKE + "/stubborn-" + case)
def should_bail():
    if os.path.exists(FAKE + "/stop-" + unit): return True
    if not stubborn() and not [e for e in load_q()["entries"] if e["state"] in ("waiting", "grouped")]: return True
    return time.time() > hard
def finish(n, st, reason, gid=None, ci=None):
    def f(q):
        for e in reversed(q["entries"]):
            if e["pr"] == n and e["state"] in ("waiting", "grouped"):
                e.update(state=st, reason=reason, group=gid, ended=int(time.time()))
                if ci: e["ci"] = ci
                return
    update_q(f)
def build(prs, onto=None):
    """the chain: each PR is merged on the entry ahead of it (the first on main, or on `onto`); returns the PRs that built and the head of each one's entry"""
    git("fetch", "-q", "origin", base); git("checkout", "-q", "--detach", onto or "origin/" + base); git("reset", "-q", "--hard", onto or "origin/" + base)
    ok, heads = [], {}
    for n in prs:
        facts = rp["prs"][str(n)]
        bad = [(k, v) for k, v in sorted(facts["checks"].items()) if v != "pass"]
        if bad: finish(n, "ejected", "refused: a check failed: " + ", ".join("%s=%s" % kv for kv in bad)); continue
        if git("fetch", "-q", "origin", facts["head"], check=False).returncode:
            finish(n, "ejected", "head %s cannot be fetched from origin" % facts["head"][:7]); continue
        if git("merge", "--no-ff", "-q", "-m", "merge #%d" % n, facts["head"], check=False).returncode:
            files = sorted(git("diff", "--name-only", "--diff-filter=U").stdout.split())
            hook, allowed = rules.get("on_conflict"), rules.get("conflict_paths", ["tests/tool_text.snapshot.json"])
            if hook and files and set(files) <= set(allowed) and subprocess.run(hook, shell=True, cwd=clone).returncode == 0:
                git("add", "-A"); git("commit", "-q", "--no-edit"); ok.append(n); heads[n] = git("rev-parse", "HEAD").stdout.strip(); continue
            git("merge", "--abort", check=False)
            finish(n, "ejected", "refused: conflicts with main (%s)" % ", ".join(files)); continue
        ok.append(n); heads[n] = git("rev-parse", "HEAD").stdout.strip()
    return ok, heads
def make_group(gid, ok, parent=None, head=None):
    gr = {"id": gid, "seq": int(gid[1:]), "phase": "built", "base": git("rev-parse", "origin/" + base).stdout.strip(), "head": head or git("rev-parse", "HEAD").stdout.strip(),
          "branch": prefix + gid, "members": ok, "run": None, "verdict": None, "parent": parent, "pushed_at": None}
    save_group(gr)
    for n in ok:
        def f(q, n=n):
            for e in reversed(q["entries"]):
                if e["pr"] == n and e["state"] == "waiting": e.update(state="grouped", group=gid)
        update_q(f)
    return gr
def runfile(gr): return FAKE + "/runs/" + gr["branch"].replace("/", "_")
def test_group(gr):
    late = os.path.exists(FAKE + "/late-" + case)
    while late and [e for e in load_q()["entries"] if e["state"] in ("waiting", "grouped")] and not os.path.exists(FAKE + "/stop-" + unit) and time.time() < hard:
        time.sleep(0.05)                       # a driver still busy with its build when its PRs are dropped: it pushes the group all the same, and CI starts
    if late: time.sleep(0.3)
    git("push", "-q", "origin", gr["head"] + ":refs/heads/" + gr["branch"]); pushed.append(gr["branch"])
    rid = 4241 + gr["seq"]
    os.makedirs(FAKE + "/runs", exist_ok=True); open(runfile(gr), "w").write(str(rid))
    if os.path.exists(FAKE + "/cancelled"): open(FAKE + "/cancelled", "w").write("".join(x + "\n" for x in open(FAKE + "/cancelled").read().split() if x != str(rid)))      # a new run under an id used before          # the run CI started for the branch, listed by `gh run list --branch` until cancelled or done
    gr.update(phase="testing", pushed_at=int(time.time()), run={"id": rid, "url": "https://github.com/%s/actions/runs/%d" % (repo, rid)}); save_group(gr)
    jlog(ev="pushed", case=case, branch=gr["branch"], run=rid)
    if late: jlog(ev="late_pushed", case=case, branch=gr["branch"]); sys.exit(0)
    while os.path.exists(FAKE + "/hold-" + case):
        if should_bail(): jlog(ev="driver_bailed", case=case); sys.exit(0)
        time.sleep(0.05)
    bad = [f for f in git("ls-tree", "-r", "--name-only", gr["head"]).stdout.split() if os.path.basename(f).startswith("BAD_")]
    os.unlink(runfile(gr))                    # the run is completed
    gr.update(phase="verdict", verdict={"result": "fail" if bad else "pass", "at": int(time.time()), "run_url": gr["run"]["url"]}); save_group(gr)
    return not bad
def unwait(n):
    def f(q):
        for e in reversed(q["entries"]):
            if e["pr"] == n and e["state"] == "grouped": e.update(state="waiting", group=None); return
    update_q(f)
def resolve(prs, parent=None, onto=None):
    """the chain: an entry per PR, each built on the one ahead (and tested in line order here); the first entry that fails drops its PR alone, and the entries behind it are rebuilt on the one ahead"""
    ok, heads = build(prs, onto)
    if not ok: return
    grs = []
    for n in ok:
        counter[0] += 1; grs.append(make_group("g%d" % counter[0], [n], parent, heads[n]))
    for i, (n, gr) in enumerate(zip(ok, grs)):
        if rp["ci"] == "skip":
            gr.update(phase="done", verdict={"result": "skipped"}); save_group(gr)
            finish(n, "tested", "tested (CI not run): entry %s was built, not pushed" % gr["id"], gr["id"], ci="skipped")
        elif test_group(gr):
            gr["phase"] = "done"; save_group(gr)
            finish(n, "tested", "entry %s passed suites (shadow: nothing was merged)" % gr["id"], gr["id"])
        else:
            gr["phase"] = "done"; save_group(gr)
            finish(n, "failed", "failed suites on its own (entry %s)" % gr["id"], gr["id"])
            for m, later in zip(ok[i + 1:], grs[i + 1:]):
                later.update(outcome="restacked", phase="done"); save_group(later); unwait(m)
            resolve(ok[i + 1:], gr["id"], heads[ok[i - 1]] if i else onto)
            return
gh = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True)           # the real driver's GitHub calls go through `gh api`, with the unit's environment
jlog(ev="driver_gh", case=case, ok=gh.returncode == 0, err=gh.stderr.strip()[:120], ci=rp["ci"], gh_config=os.path.realpath(xc + "/gh") if os.path.exists(xc + "/gh") else None)
if rp["ci"] == "real" and gh.returncode != 0:
    for e in load_q()["entries"]:
        if e["state"] == "waiting": finish(e["pr"], "failed", "gh: " + gh.stderr.strip()[:100])
    sys.exit(0)
resolve([e["pr"] for e in load_q()["entries"] if e["state"] == "waiting"])
if os.path.exists(FAKE + "/leave"): jlog(ev="driver_left", case=case, branches=pushed)
else:
    for b in pushed: git("push", "-q", "origin", "--delete", b, check=False)
jlog(ev="driver_done", case=case)
'''
FAKE_SYSTEMCTL = r'''#!%PY%
import os, sys
FAKE = os.environ["FAKE_DIR"]; a = sys.argv[1:]
if a[:1] == ["--user"]: a = a[1:]
def alive(unit):
    try: pid = int(open(FAKE + "/units/" + unit + ".pid").read())
    except (OSError, ValueError): return False
    try: st = open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()[0]
    except OSError: return False
    return st != "Z"
if a[0] == "list-units":
    pat = a[-1]
    if pat.startswith("mq-"):                       # driver units: the live ones that match the pattern
        import fnmatch
        for f in sorted(os.listdir(FAKE + "/units")):
            u = f.removesuffix(".pid")
            if fnmatch.fnmatch(u, pat) and alive(u): print("%s loaded active running merge queue driver" % u)
    elif os.path.exists(FAKE + "/release_units"): sys.stdout.write(open(FAKE + "/release_units").read())
    sys.exit(0)
if a[0] == "is-active":
    ok = alive(a[1]); print("active" if ok else "inactive"); sys.exit(0 if ok else 3)
if a[0] == "stop":
    open(FAKE + "/stop-" + a[1].removesuffix(".service") + ".service", "w").write("x"); open(FAKE + "/stopped.log", "a").write(a[1] + "\n"); sys.exit(0)
sys.exit(1)
'''
FAKE_GH = r'''#!%PY%
import json, os, sys
FAKE = os.environ["FAKE_DIR"]
a = sys.argv[1:]
open(FAKE + "/gh.log", "a").write(json.dumps(a) + "\n")
d = os.environ.get("GH_CONFIG_DIR") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "gh")
if not os.path.isfile(d + "/hosts.yml"):             # the real gh: no login reachable from this environment
    print("You are not logged into any GitHub hosts. To log in, run: gh auth login", file=sys.stderr); sys.exit(4)
cancelled = open(FAKE + "/cancelled").read().split() if os.path.exists(FAKE + "/cancelled") else []
if a[:2] == ["run", "list"] and "--branch" in a:
    f = FAKE + "/runs/" + a[a.index("--branch") + 1].replace("/", "_")
    delay = float(open(FAKE + "/run-delay").read()) if os.path.exists(FAKE + "/run-delay") else 0.0       # GitHub lists a run a little after the push
    import time
    if os.path.exists(f) and time.time() - os.path.getmtime(f) >= delay and open(f).read().strip() not in cancelled: print(open(f).read().strip())
if a[:2] == ["run", "cancel"]: open(FAKE + "/cancelled", "a").write(a[2] + "\n"); open(FAKE + "/cancel.log", "a").write(a[2] + "\n")
sys.exit(0)
'''
FAKE_SYSTEMD_RUN = r'''#!%PY%
import json, os, sys
FAKE = os.environ["FAKE_DIR"]
open(FAKE + "/systemd_run.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
sys.exit(1 if os.path.exists(FAKE + "/systemd_run_fail") else 0)
'''
for name, text in (("salamander", FAKE_SAL), ("systemctl", FAKE_SYSTEMCTL), ("gh", FAKE_GH), ("systemd-run", FAKE_SYSTEMD_RUN)):
    (BIN / name).write_text(text.replace("%PY%", sys.executable)); (BIN / name).chmod(0o755)

# ---------------------------------------------------------------- the git world
WC = ROOT / "work"; ORIGIN = ROOT / "origin.git"; WC.mkdir()
g(WC, "init", "-q", "-b", "main")
def put(path, content): (WC / path).parent.mkdir(parents=True, exist_ok=True); (WC / path).write_text(content)
def commit(msg): g(WC, "add", "-A"); g(WC, "commit", "-q", "-m", msg); return g(WC, "rev-parse", "HEAD")
RULES_TOML = ('base = "main"\nrequired = ["suites"]\nqueue_prefix = "queue/main/"\ngroup_max = 4\ninflight_max = 2\nbisect = true\nqueue_mode = "chain"\n'
              'on_conflict = "sh -c \'echo regenerated > snapshot.json\'"\nconflict_paths = ["snapshot.json"]\n')
put(".github/mergequeue.toml", RULES_TOML); put("a.txt", "base\n"); put("snapshot.json", "base\n"); put("README", "r\n")
B = commit("base")
def pr_head(name, files, start=B):
    g(WC, "checkout", "-q", "-b", name, start)
    for p, c in files.items(): put(p, c)
    h = commit(name); g(WC, "checkout", "-q", "main"); return h
H = {n: pr_head(f"pr{n}", {f"f{n}.txt": f"{n}\n"}) for n in (101, 102, 106, 108, 110, 111, 112, 801, 802, 803)}
H[103] = H[101]                                                                       # t03: the same head, a wrong recorded tree
H[702] = pr_head("pr702", {"BAD_y.txt": "x\n", "f702.txt": "x\n"}); H[701] = pr_head("pr701", {"f701.txt": "1\n"})
H[104] = pr_head("pr104", {"a.txt": "head change\n"})
H[109] = pr_head("pr109", {"snapshot.json": "head\n", "f109.txt": "x\n"})
H[1021] = pr_head("pr1021", {"BAD_x.txt": "x\n", "f1021.txt": "x\n"})
put("a.txt", "main change\n"); B2 = commit("main: a.txt")
put("snapshot.json", "main\n"); B3 = commit("main: snapshot.json")
MT = [0]
def merged_tree(base, head, resolve=None):
    """the tree of the merge of head into base, as the old path made it (a side branch; the resolution of a snapshot-only conflict if given)"""
    MT[0] += 1; g(WC, "checkout", "-q", "-b", f"m{MT[0]}-" + head[:7], base)
    r = subprocess.run([REAL_GIT, "-C", str(WC), *AUTHOR, "merge", "--no-ff", "-q", "-m", "m", head], capture_output=True, text=True, env={**BASE_ENV, "PATH": os.environ["PATH"]})
    if r.returncode and resolve:
        for p, c in resolve.items(): put(p, c)
        g(WC, "add", "-A"); g(WC, "commit", "-q", "--no-edit")
    t = g(WC, "rev-parse", "HEAD^{tree}"); g(WC, "checkout", "-q", "main"); return t
def pr(n, head, outcome, base=None, **kw):
    d = {"pr": n, "attempt": 0, "known_outcome": outcome, "head": head, "base": base or B, "checks": {"suites": "pass"}, "branch": f"feat-{n}"}
    if outcome == "merged": d.update(head_mode="peeled", merge="a" * 40, merge_tree="b" * 40, main_run={"result": "pass", "run": 41400000000 + n, "on": "c" * 40, "flaky": []})
    d.update(kw); return d
def case(cid, prs, **kw):
    c = {"id": cid, "kind": "group" if len(prs) > 1 else prs[0]["known_outcome"], "prs": prs, "base": prs[0]["base"]}
    if len(prs) == 1:
        c["known_outcome"] = prs[0]["known_outcome"]; c["expected_tree"] = prs[0].get("merge_tree") if prs[0]["known_outcome"] == "merged" else None
    c.update(kw); return c
def single_merged(cid, n, head=None, **kw):
    h = head or H[n]; t = merged_tree(B, h)
    return case(cid, [pr(n, h, "merged", merge_tree=t)])
CASES = [
    single_merged("t01", 101),                                                                      # match
    single_merged("t02", 1021, H[1021]),                                                            # the head carries a BAD_ file: CI fails a PR the old path merged
    case("t03", [pr(103, H[103], "merged", merge_tree=merged_tree(B, H[101]))]),                    # fixed up below: wrong recorded tree
    case("t04", [pr(104, H[104], "refused", base=B2, stage="mergeable", reason="CONFLICTING", expected_reason="refused: conflicts with main (a.txt)", conflict_files=["a.txt"])]),
    case("t05", [pr(105 if False else 1050, H[102], "refused", checks={"suites": "fail"}, owner="fork-user", stage="checks", reason="a check failed: suites=fail",
                    expected_reason="refused: a check failed: suites=fail")]),
    case("t06", [pr(106, H[106], "refused", stage="checks", reason="a check failed: suites=fail", expected_reason="refused: a check failed: suites=fail")]),      # the queue accepts it
    case("t07", [pr(701, H[701], "merged", merge_tree="d" * 40), pr(702, H[702], "refused", checks={}, expect="fails alone: this PR is dropped as failed on its own and the others pass", stage="checks", reason="a check failed: suites=fail",
                                                                      checks_note="left out on purpose")], note="fails-alone pair"),
    case("t08", [pr(n, H[n], "merged", merge_tree="d" * 40) for n in (801, 802, 803)]),
    case("t09", [pr(109, H[109], "merged", base=B3, head_mode="queue", merge_tree=merged_tree(B3, H[109], {"snapshot.json": "regenerated\n"}))]),
    single_merged("t10", 110), single_merged("t11", 111), single_merged("t12", 112),
]
CASES[2]["expected_tree"] = CASES[2]["prs"][0]["merge_tree"] = merged_tree(B, H[102])           # t03: the PR 103 head is the one of PR 101, the recorded tree is the one of PR 102
CASES[2]["prs"][0]["pr"] = 103
CASES[4]["prs"][0]["pr"] = 105
g(ROOT, "init", "-q", "--bare", "-b", "main", str(ORIGIN)); g(ORIGIN, "config", "uploadpack.allowAnySHA1InWant", "true")
g(WC, "remote", "add", "origin", f"file://{ORIGIN}")
g(WC, "push", "-q", "-u", "origin", "main")
for n, h in H.items(): g(WC, "push", "-q", "origin", f"{h}:refs/pull/{n}/head")                  # the PR heads are on origin on no branch, as for closed PRs
for f_ in (WC / ".git" / "refs" / "heads").iterdir(): pass
CASES_FILE = ROOT / "cases.json"; CASES_FILE.write_text(json.dumps({"format": 1, "trigger": B, "cases": CASES, "dropped": []}, indent=1))
POLICY_LOG = FAKE / "pushes.log"
hook = ORIGIN / "hooks" / "pre-receive"
hook.write_text(f'#!/bin/sh\nwhile read old new ref; do echo "$ref $old $new" >> "{POLICY_LOG}"; done\n'); hook.chmod(0o755)

def origin_refs(): return g(ORIGIN, "for-each-ref", "--format=%(refname) %(objectname)")
def practice_refs(): return [ln.split()[0] for ln in origin_refs().splitlines() if re.match(r"refs/heads/(queue/)?practice/", ln)]
MAIN_BEFORE = g(ORIGIN, "rev-parse", "refs/heads/main")
REFS_BEFORE = origin_refs()
DECOY = OUTER_STATE / "mergequeue" / SLUG.replace("/", "__"); (DECOY / "groups").mkdir(parents=True)
(DECOY / "queue.json").write_text('{"entries": [{"pr": 1, "state": "waiting"}], "next_seq": 9}\n'); (DECOY / "groups" / "g9.json").write_text('{"id": "g9", "phase": "testing"}\n')
(DECOY / "events.log").write_text('{"ev": "decoy"}\n')
(OUTER_STATE / "salamander" / "ci-runs").mkdir(parents=True); (OUTER_STATE / "salamander" / "ci-runs" / "x.json").write_text("{}\n")
def tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(pathlib.Path(path).rglob("*")): h.update(str(p.relative_to(path)).encode() + (p.read_bytes() if p.is_file() else b"/"))
    return h.hexdigest()
DECOY_HASH = tree_hash(DECOY)
GH_HASH = tree_hash(OUTER_CONF / "gh")

COMMON = ["--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG, "--cases-file", str(CASES_FILE), "--gate-poll", "0.2", "--gate-cap", "30", "--driver-wait", "3", "--settle", "0.3",
          "--case-timeout", "90"]
def tool(*args, timeout=180, env=None):
    return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, env={**ENV, **(env or {})}, timeout=timeout, cwd=str(ROOT))
def run_tool(run_id, *extra, **kw): return tool("run", "--run", run_id, *COMMON, *extra, **kw)
def popen(run_id, *extra, out="out"):
    fo, fe = open(ROOT / f"{run_id}.{out}", "w"), open(ROOT / f"{run_id}.err", "w")
    return subprocess.Popen([sys.executable, TOOL, "run", "--run", run_id, *COMMON, *extra], stdout=fo, stderr=fe, env=ENV, cwd=str(ROOT), text=True)
def calls(**match): return [c for c in (json.loads(x) for x in (FAKE / "calls.log").read_text().splitlines()) if all(c.get(k) == v for k, v in match.items())] if (FAKE / "calls.log").exists() else []
def runjson(run_id): return json.loads((OUTER_STATE / "stackshot" / "mq-replay" / run_id / "run.json").read_text())
def report(run_id): return (OUTER_STATE / "stackshot" / "mq-replay" / run_id / "report.md").read_text()
def rows(run_id): return {ln.split("|")[1].strip(): [c.strip() for c in ln.strip().strip("|").split("|")] for ln in report(run_id).splitlines() if re.match(r"\| t\d\d ", ln)}
def wait_for(cond, secs=30):
    end = time.time() + secs
    while time.time() < end:
        if cond(): return True
        time.sleep(0.1)
    return cond()
def case_dirs(run_id): d = OUTER_STATE / "stackshot" / "mq-replay" / run_id / "cases"; return sorted(p.name for p in d.iterdir()) if d.exists() else []
def term(proc):
    """SIGTERM to the tool this test started (checked by its /proc exe: the test's own interpreter, never a process found by name)"""
    assert os.path.realpath(f"/proc/{proc.pid}/exe") == os.path.realpath(sys.executable), "not the process this test started"
    proc.send_signal(signal.SIGTERM)

spec = importlib.util.spec_from_file_location("mq_replay_run_tool", MOD); sys.path.insert(0, os.path.dirname(MOD)); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

try:
    # ============================================================ the guard and the gate, unit level
    good = ["refs/heads/practice/r1/c01", "refs/heads/queue/practice/r1/c01/g1", "refs/heads/practice/20261103T051200Z/c13"]
    bad = ["refs/heads/main", "refs/heads/practice/../main", "refs/heads/feat/practice/r1/c01", "refs/heads/queue/main/g1", "refs/tags/practice/r1/c01", "refs/heads/practice/", "refs/heads/practice",
           "refs/heads/practice-old/x", "refs/heads/queue/practice", "refs/pull/1/head", "practice/r1/c01", "refs/heads/practice/r1/.hidden", "refs/heads/practice/r1/x.lock", "+refs/heads/practice/r1/c01",
           "refs/heads/practice/r1/c01 refs/heads/main", "refs/heads/practice/r1/c01:refs/heads/main", "", None]
    check("check_ref accepts practice/ and queue/practice/ branches", all(mod.check_ref(r) == r for r in good))
    def refused(r):
        try: mod.check_ref(r); return False
        except mod.RefGuardError: return True
    check("check_ref refuses main, PR refs, tags, look-alikes, dot and .lock names and refspec tricks", all(refused(r) for r in bad), [r for r in bad if not refused(r)])
    rem = mod.Remote(f"file://{ORIGIN}", ROOT / "unit-push.git", str(WC))
    for refn in bad[:6]:
        try: rem.create(B, refn); ok_ = False
        except mod.RefGuardError: ok_ = True
        check(f"Remote.create refuses {refn!r} before any git call", ok_)
    rem.create(B, "refs/heads/practice/unit/c01")
    check("Remote.create pushes a practice base", "refs/heads/practice/unit/c01" in practice_refs())
    try: rem.delete(["refs/heads/practice/unit/c01", "refs/heads/main"]); ok_ = False
    except mod.RefGuardError: ok_ = True
    check("Remote.delete is all or nothing: one guarded ref refuses the whole call", ok_ and "refs/heads/practice/unit/c01" in practice_refs() and g(ORIGIN, "rev-parse", "refs/heads/main") == MAIN_BEFORE)
    check("Remote.delete removes a practice ref and reports none left", rem.delete(["refs/heads/practice/unit/c01"]) == [] and practice_refs() == [])
    shutil.rmtree(ROOT / "unit-push.git")

    ns = type("N", (), {})()
    ns.systemctl, ns.salamander, ns.gh = "systemctl", "salamander", "gh"
    ctx_ = type("C", (), {"systemctl": "systemctl", "salamander": "salamander", "slug": SLUG, "logdir": LOGS, "gate_poll": 0.1})()
    os.environ.update(PATH=ENV["PATH"], FAKE_DIR=str(FAKE), XDG_STATE_HOME=str(OUTER_STATE), XDG_CONFIG_HOME=str(OUTER_CONF), STACKSHOT_CONFIG=str(INSTANCE_CONFIG))
    gate = mod.Gate(ctx_)
    check("the gate is open on an idle box", gate.raw() == [], gate.raw())
    (FAKE / "release_units").write_text("stackshot-release-9.service loaded active running stackshot release of PR 9\n")
    r_ = gate.raw(); check("a running stackshot-release-*.service closes the gate", len(r_) == 1 and "stackshot-release-9.service" in r_[0], r_)
    (FAKE / "release_units").write_text("● stackshot-mq-shadow-9-1.service loaded active running waiter\n")
    check("a shadow comparison unit is only a waiter and does not close it", gate.raw() == [])
    (FAKE / "release_units").unlink()
    (LOGS / "queue").write_text("12\n13\n"); r_ = gate.raw(); check("a non-empty release queue file closes the gate", len(r_) == 1 and "release queue holds 2" in r_[0], r_)
    (LOGS / "queue").write_text("\n"); check("an empty release queue file does not", gate.raw() == [])
    (FAKE / "real_status.json").write_text(json.dumps({"groups": [{"id": "g41", "phase": "testing"}, {"id": "g40", "phase": "done"}]}))
    r_ = gate.raw(); check("a real merge-queue group in testing closes the gate", len(r_) == 1 and "g41" in r_[0], r_)
    (FAKE / "real_status.json").write_text(json.dumps({"groups": [{"id": "g40", "phase": "done"}]})); check("finished real groups do not", gate.raw() == [])
    for ph in ("building", "built", "pushed", "testing", "verdict", "merging", "cleaning"):
        (FAKE / "real_status.json").write_text(json.dumps({"groups": [{"id": "g50", "phase": ph}]})); r_ = gate.raw()
        check(f"a real group in phase {ph} closes the gate", len(r_) == 1 and "g50" in r_[0], r_)
    (FAKE / "real_status.json").write_text(json.dumps({"groups": [{"id": "g50", "phase": "done"}]})); check("a real group in phase done does not", gate.raw() == [])
    sal_state = pathlib.Path.home() / "salamander" / "lib" / "mq" / "mq_state.py"
    if sal_state.exists():
        m_ = re.search(r"^PHASES = \(([^)]*)\)", sal_state.read_text(), re.M)
        check("LIVE_PHASES is every phase of salamander's PHASES but done", m_ and set(mod.LIVE_PHASES) == set(re.findall(r'"(\w+)"', m_.group(1))) - {"done"}, (mod.LIVE_PHASES, m_ and m_.group(1)))
    (FAKE / "real_status_fail").write_text("x"); r_ = gate.raw(); check("a status call that fails cannot show the box is idle: the gate stays shut", len(r_) == 1 and "cannot tell" in r_[0], r_)
    (FAKE / "real_status_fail").unlink(); (FAKE / "real_status.json").unlink()
    check("the gate asked the real queue without a case's state folder", all(c["xdg_state"] == str(OUTER_STATE) for c in calls(ev="real_status")) and calls(ev="real_status"))
    check("the release folder is the one release.sh uses: `config.py state releases` of the instance config (STACKSHOT_CONFIG here)", mod.default_logdir() == LOGS, mod.default_logdir())
    sys.stdout.flush()

    # ============================================================ the verdict rules, unit level
    mk = lambda **k: {"pr": 1, "known_outcome": "refused", **k}
    exp_c = "refused: a check failed: tool-text-model=fail, suites=pending"
    check("reason_matches: the same check names in another order match", mod.reason_matches(exp_c, "refused: a check failed: suites=pending, tool-text-model=fail")[0])
    check("reason_matches: other check names do not", not mod.reason_matches(exp_c, "refused: a check failed: suites=fail")[0])
    check("reason_matches: a conflict names the same files", mod.reason_matches("refused: conflicts with main (a, b)", "refused: conflicts with main (b, a)")[0]
          and not mod.reason_matches("refused: conflicts with main (a)", "refused: conflicts with main (b)")[0] and not mod.reason_matches("refused: conflicts with main (a)", "refused: a check failed: x=fail")[0])
    one = lambda p: {"id": "x", "kind": p["known_outcome"], "prs": [p]}
    check("judge: a merged PR is exit 3 with CI and exit 4 without", mod.judge_pr(one(mk(known_outcome="merged")), mk(known_outcome="merged"), {"exit": 3}, False)[0]
          and mod.judge_pr(one(mk(known_outcome="merged")), mk(known_outcome="merged"), {"exit": 4}, True)[0] and not mod.judge_pr(one(mk(known_outcome="merged")), mk(known_outcome="merged"), {"exit": 4}, False)[0])
    ok_, _, side = mod.judge_pr(one(mk(known_outcome="merged")), mk(known_outcome="merged"), {"exit": 1, "state": "failed", "reason": "group g1 failed suites", "link": "https://x/runs/1"}, False)
    check("judge: a merged PR whose group failed says to look at CI and names the run", not ok_ and "look at CI" in side and "https://x/runs/1" in side, side)
    ok_, _, side = mod.judge_pr(one(mk(known_outcome="merged")), mk(known_outcome="merged"), {"exit": 1, "state": "ejected", "reason": "refused: conflicts with main (a.txt)"}, False)
    check("judge: a merged PR the queue says conflicts points at the queue's merge", not ok_ and "look at the queue" in side, side)
    ok_, _, side = mod.judge_pr(one(mk()), mk(expected_reason="refused: a check failed: suites=fail"), {"exit": 3, "state": "tested"}, False)
    check("judge: a refused PR the queue passed points at the old path or the fixture", not ok_ and "old path or the fixture" in side, side)
    ok_, _, side = mod.judge_pr(one(mk()), mk(expected_reason="refused: a check failed: suites=fail"), {"exit": 2, "reason": "gave up"}, False)
    check("judge: no verdict is a mismatch that says to rerun", not ok_ and "--resume" in side, side)
    grp = {"id": "x", "kind": "group", "prs": []}
    check("fail_alone_expected reads the fixture's `expect` field (`fails alone: ...`) and nothing else: no checks and a group are not enough, nor is a key that merely has fails_alone in its name",
          mod.fail_alone_expected(grp, mk(expect="fails alone: this PR is dropped as failed")) and not mod.fail_alone_expected(grp, mk(checks={})) and not mod.fail_alone_expected(grp, mk(expected_fails_alone=True))
          and not mod.fail_alone_expected(grp, mk(expect="the group passes")) and not mod.fail_alone_expected(grp, mk()))
    check("needs_ci: a merged PR or a group, not a lone refusal", mod.needs_ci({"kind": "merged", "prs": [mk(known_outcome="merged")]}) and mod.needs_ci(grp) and not mod.needs_ci({"kind": "refused", "prs": [mk()]}))
    import threading, types
    (ROOT / "rs-unit").mkdir()
    cx_ = types.SimpleNamespace(rundir=ROOT / "rs-unit", remote_url=f"file://{ORIGIN}", repo=str(WC), run_id="rsu", systemctl="systemctl", salamander="salamander", slug=SLUG, logdir=LOGS, gate_poll=0.1)
    rp_ = mod.Replay(None, cx_, [], {"profile": "build"}, True)
    log0 = (ROOT / "rs-unit" / "run.log").stat().st_size
    held, release_ = threading.Event(), threading.Event()
    def holder():
        with rp_.lock: held.set(); release_.wait(20)
    th_ = threading.Thread(target=holder, daemon=True); th_.start(); held.wait(5)
    done_ = threading.Event()
    def handler(): rp_.request_stop("signal", "terminated (SIGTERM)"); done_.set()
    threading.Thread(target=handler, daemon=True).start()
    check("the signal handler's entry (request_stop) takes no lock and writes nothing: it returns while another holder has the run's lock, and the stop is set",
          done_.wait(3) and rp_.stop.is_set() and not isinstance(rp_.stop, threading.Event) and rp_.stop_kind == "signal" and (ROOT / "rs-unit" / "run.log").stat().st_size == log0, (done_.is_set(), rp_.stop.is_set()))
    release_.set(); th_.join(5)
    rp_.logf.close()
    shutil.rmtree(ROOT / "rs-unit")

    # ============================================================ the 20 real cases
    if os.path.exists(CASES_REAL):
        real = json.loads(open(CASES_REAL).read())["cases"]
        allowed = {"version", "run", "case", "ci", "rules", "prs"}; pr_allowed = {"state", "draft", "head", "branch", "owner", "checks"}
        docs = [(c, mod.build_replay_doc(c, "r1", "skip", "acme-org", {"required": ["suites"]})) for c in real]
        check("every real case makes a replay file of exactly the schema's keys, full shas, valid check states, a practice base and prefix",
              all(set(d) == allowed and d["rules"]["base"] == f"practice/r1/{c['id']}" and d["rules"]["queue_prefix"] == f"queue/practice/r1/{c['id']}/" and
                  all(set(p) == pr_allowed and re.fullmatch(r"[0-9a-f]{40}", p["head"]) and p["owner"] and p["branch"] and all(v in ("pass", "fail", "pending", "cancel") for v in p["checks"].values())
                      for p in d["prs"].values()) for c, d in docs))
        check("a real case that records no owner gets the repository's owner, and the rules are a chain with no group keys", all(p["owner"] == "acme-org" for c, d in docs for k, p in d["prs"].items()
                                                                                                             if not next(x for x in c["prs"] if str(x["pr"]) == k).get("owner")) and
              all(d["rules"].get("queue_mode") == "chain" and not {"group_max", "bisect"} & set(d["rules"]) for c, d in docs))
        need = [c["id"] for c in real if mod.needs_ci(c)]
        check("the CI cases of the real file are c01 to c13", need == [f"c{i:02d}" for i in range(1, 14)], need)
        bis = [(c["id"], p["pr"]) for c in real for p in c["prs"] if mod.fail_alone_expected(c, p)]
        check("exactly one real PR is a fails-alone expectation: the one of c13 (PR 10)", bis == [("c13", 10)], bis)
    else:
        check("the real cases file exists", False)

    # ============================================================ build profile: every kind of row, no CI
    r = run_tool("b1", "--profile", "build", "--cases", "t01,t02,t03,t04,t05,t06,t07,t08,t09")
    R1 = rows("b1")
    check("build run: exit 1 because two rows do not match", r.returncode == 1, (r.returncode, r.stderr[-1500:]))
    check("build: the clean merged PR matches (exit 4, tree = M's)", R1["t01"][5] == "yes" and "exit 4" in R1["t01"][4] and "tree = M's" in R1["t01"][6], R1.get("t01"))
    check("build: a BAD_ head is not tested without CI, so it matches", R1["t02"][5] == "yes", R1.get("t02"))
    check("build: a wrong recorded tree is a NO that names the queue's hook / the tree", R1["t03"][5] == "NO" and "tree" in R1["t03"][6], R1.get("t03"))
    check("build: a conflict ejection matches with the files (refused: conflicts with main (a.txt))", R1["t04"][5] == "yes" and "conflicts with main (a.txt)" in R1["t04"][4], R1.get("t04"))
    check("build: a check refusal matches with the check names", R1["t05"][5] == "yes" and "suites=fail" in R1["t05"][4], R1.get("t05"))
    check("build: a refusal the queue accepts is a NO that says old path or fixture", R1["t06"][5] == "NO" and "old path or the fixture" in R1["t06"][6], R1.get("t06"))
    check("build: the fails-alone pair is exit 4 for both (a failure needs CI) and matches", R1["t07"][5] == "yes" and R1["t07"][4].count("exit 4") == 2, R1.get("t07"))
    check("build: a group of three matches", R1["t08"][5] == "yes" and R1["t08"][4].count("exit 4") == 3, R1.get("t08"))
    check("build: the snapshot-only conflict is mended by the rules' on_conflict and the tree = M's (head replayed at queue time)", R1["t09"][5] == "yes" and "queue-time head" in R1["t09"][6], R1.get("t09"))
    check("the table has the design's columns, the head -> base cell and the old path's outcome",
          "| case | PR(s) | head -> base | known outcome (old path) | queue verdict | match | note |" in report("b1") and f"{H[101][:7]} -> {B[:7]}" in R1["t01"][2] and "merged" in R1["t01"][3], report("b1")[:900])
    check("stdout carries the same table and the report path", "| t09 |" in r.stdout and "report:" in r.stdout)
    add = {c["case"]: c for c in calls(ev="add") if c["run"] == "b1"}
    d1 = add["t01"]["replay"]
    check("replay.json: version 1, run and case, ci skip in the build profile, rules from the repository's file with the practice base and prefix",
          d1["version"] == 1 and d1["run"] == "b1" and d1["case"] == "t01" and d1["ci"] == "skip" and d1["rules"]["base"] == "practice/b1/t01" and d1["rules"]["queue_prefix"] == "queue/practice/b1/t01/"
          and d1["rules"]["required"] == ["suites"] and d1["rules"]["queue_mode"] == "chain" and "group_max" not in d1["rules"] and "bisect" not in d1["rules"] and "snapshot.json" in d1["rules"]["on_conflict"], d1)
    check("replay.json: the owner is filled from the repository, an explicit owner is kept, heads are the recorded shas",
          d1["prs"]["101"]["owner"] == "acme-org" and add["t05"]["replay"]["prs"]["105"]["owner"] == "fork-user" and d1["prs"]["101"]["head"] == H[101]
          and d1["prs"]["101"]["state"] == "OPEN" and d1["prs"]["101"]["draft"] is False, d1["prs"]["101"])
    check("host file: mode shadow, the remote, a clone inside the case's folder, the replay path", 'mode = "shadow"' in add["t01"]["host"] and f'remote = "file://{ORIGIN}"' in add["t01"]["host"]
          and "/cases/t01/clone" in add["t01"]["host"] and "/cases/t01/replay.json" in add["t01"]["host"], add["t01"]["host"])
    check("each case ran with its own XDG folders under the run, never the outer ones", all(c["xdg_state"].endswith(f"/b1/cases/{c['case']}/state") and c["xdg_config"].endswith(f"/b1/cases/{c['case']}/config") for c in add.values()))
    check("the CI-run poller's folder is linked into the case's state (a wait costs no GitHub call)", all(c["poller_link"] for c in add.values()))
    check("a group's PRs go to one `mq add`; the replay rules run it as a chain without the retired group keys", add["t08"]["prs"] == [801, 802, 803] and add["t08"]["replay"]["rules"]["queue_mode"] == "chain" and not {"group_max", "bisect"} & set(add["t08"]["replay"]["rules"]))
    check("cleanup (build): no practice ref on origin, no case folder, no push scratch repository", practice_refs() == [] and case_dirs("b1") == [] and not (OUTER_STATE / "stackshot" / "mq-replay" / "b1" / "push.git").exists())
    check("cleanup: the replay run's lock file is the only thing besides its records", sorted(p.name for p in (OUTER_STATE / "stackshot" / "mq-replay" / "b1").iterdir()) == ["cases", "report.md", "run.json", "run.lock", "run.log"]
          or sorted(p.name for p in (OUTER_STATE / "stackshot" / "mq-replay" / "b1").iterdir()) == ["report.md", "run.json", "run.lock", "run.log"], sorted(p.name for p in (OUTER_STATE / "stackshot" / "mq-replay" / "b1").iterdir()))

    # ============================================================ full profile: real CI
    r = run_tool("f1", "--profile", "full", "--cases", "t01,t02,t07,t08,t09")
    R2 = rows("f1")
    check("full run: exit 1 (t02 does not match)", r.returncode == 1, (r.returncode, r.stderr[-1500:]))
    check("full: a clean merged PR is exit 3 with the tree = M's, and the row carries the run link and minutes", R2["t01"][5] == "yes" and "exit 3" in R2["t01"][4] and "actions/runs/4242" in R2["t01"][4] and "min" in R2["t01"][4], R2.get("t01"))
    check("full: CI failing a PR the old path merged is a NO that says look at CI", R2["t02"][5] == "NO" and "look at CI" in R2["t02"][6] and "entry g1" in R2["t02"][4], R2.get("t02"))
    check("full: the fails-alone pair: the failing PR is named failed, its mate passes, and the row matches", R2["t07"][5] == "yes" and f"#{701} exit 3 tested" in R2["t07"][4] and f"#{702} exit 1 failed" in R2["t07"][4]
          and "on its own" in R2["t07"][4], R2.get("t07"))
    check("full: a group of three passes in one group", R2["t08"][5] == "yes" and R2["t08"][4].count("exit 3") == 3, R2.get("t08"))
    check("full: the mended snapshot conflict passes CI with the tree = M's", R2["t09"][5] == "yes" and "exit 3" in R2["t09"][4], R2.get("t09"))
    check("full: ci real for the cases that run", {c["case"]: c["ci"] for c in calls(ev="add") if c["run"] == "f1"} == {k: "real" for k in ("t01", "t02", "t07", "t08", "t09")})
    pushed_refs = {ln.split()[0] for ln in POLICY_LOG.read_text().splitlines()}
    check("full: the chain pushed an entry per PR (g1 and g2), and every one was deleted again", all(f"refs/heads/queue/practice/f1/t07/g{i}" in pushed_refs for i in (1, 2)) and practice_refs() == [])
    check("full: a normal run cancels no CI", not (FAKE / "gh.log").exists() or "cancel" not in (FAKE / "gh.log").read_text())
    dg = [c for c in calls(ev="driver_gh") if c["ci"] == "real"]
    check("gh login: every real-CI driver reached the real gh login from its own XDG_CONFIG_HOME (a link to the real gh config folder, not a copy)", dg and all(c["ok"] and c["gh_config"] == os.path.realpath(OUTER_CONF / "gh") for c in dg), dg[:2])
    nogh = subprocess.run(["gh", "api", "rate_limit"], capture_output=True, text=True, env={**ENV, "XDG_CONFIG_HOME": str(ROOT / "empty-config")})
    check("the fake gh refuses without a login reachable from its environment (so a driver without the link would fail every real-CI case)", nogh.returncode == 4 and "not logged into any GitHub hosts" in nogh.stderr, nogh.stderr)
    check("gh login: the real gh config folder is byte-identical after the runs and their cleanups (links removed, nothing behind them touched)", tree_hash(OUTER_CONF / "gh") == GH_HASH and (OUTER_CONF / "gh" / "hosts.yml").is_file())

    # ============================================================ isolation
    check("isolation: the decoy mergequeue folder is byte-identical after every run", tree_hash(DECOY) == DECOY_HASH)
    check("isolation: the fake salamander was never given the real state folder", calls(ev="WROTE_REAL_STATE") == [])
    check("isolation: origin's main did not move", g(ORIGIN, "rev-parse", "refs/heads/main") == MAIN_BEFORE)
    check("isolation: the PR refs and every other ref are untouched; nothing is left but them", origin_refs() == REFS_BEFORE, origin_refs())
    touched = {ln.split()[0] for ln in POLICY_LOG.read_text().splitlines()}
    check("isolation: every ref anything created, moved or deleted on origin is practice/ or queue/practice/", touched and all(re.fullmatch(r"refs/heads/(queue/)?practice/.+", t) for t in touched), sorted(touched)[:6])
    zero = "0" * 40
    log_rows = [ln.split() for ln in POLICY_LOG.read_text().splitlines()]
    check("isolation: each ref was created and then deleted (added, then removed)", all(any(x[0] == t and x[1] == zero for x in log_rows) and any(x[0] == t and x[2] == zero for x in log_rows) for t in touched))

    # ============================================================ the idle gate at the start
    (FAKE / "release_units").write_text("stackshot-release-9.service loaded active running release of PR 9\n")
    p = popen("gate1", "--cases", "t01")
    time.sleep(1.5)
    check("idle gate at start: a release going means nothing is started (no practice ref, no mq add) and the run waits", p.poll() is None and practice_refs() == [] and not [c for c in calls(ev="add") if c["run"] == "gate1"])
    (FAKE / "release_units").unlink()
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    err_ = (ROOT / "gate1.err").read_text()
    check("idle gate at start: the release ends, the run goes on and finishes with a matching row", p.returncode == 0 and rows("gate1")["t01"][5] == "yes", (p.returncode, err_[-600:]))
    check("idle gate at start: the wait is told on stderr with the unit", "waiting for the box to be idle" in err_ and "stackshot-release-9.service" in err_, err_[:400])

    (LOGS / "queue").write_text("612\n")
    p = popen("gateq", "--cases", "t01")
    time.sleep(1.5)
    check("idle gate (queue file in the instance's release folder): a queued release holds the run back", p.poll() is None and not [c for c in calls(ev="add") if c["run"] == "gateq"])
    (LOGS / "queue").write_text("")
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    check("idle gate (queue file): the queue empties, the run goes on and matches; the wait named the release queue", p.returncode == 0 and rows("gateq")["t01"][5] == "yes" and "release queue holds 1 PR" in (ROOT / "gateq.err").read_text(), (p.returncode, (ROOT / "gateq.err").read_text()[-400:]))

    # ============================================================ the idle gate mid-run, then --resume
    (FAKE / "hold-t10").write_text("x")
    p = popen("mid1", "--profile", "full", "--concurrency", "1", "--cases", "t01,t10,t11")
    check("mid-run: the second case is really in flight (its group branch is on origin)", wait_for(lambda: "refs/heads/queue/practice/mid1/t10/g1" in practice_refs(), 40), (practice_refs(), (ROOT / "mid1.err").read_text()[-500:]))
    (FAKE / "release_units").write_text("stackshot-release-77.service loaded active running release of PR 77\n")
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    err_ = (ROOT / "mid1.err").read_text()
    st = runjson("mid1")["cases"]
    check("mid-run: a release appearing ends the run with exit 75 and says how to resume", p.returncode == 75 and "--resume mid1" in err_, (p.returncode, err_[-600:]))
    check("mid-run: t01 finished, t10 is interrupted, t11 was never started", st["t01"]["status"] == "done" and st["t10"]["status"] == "interrupted" and st["t11"]["status"] == "pending", {k: v["status"] for k, v in st.items()})
    check("mid-run: its own CI run was cancelled with gh run cancel", '"cancel", "4242"' in (FAKE / "gh.log").read_text().replace("[", "").replace("]", "") or '["run", "cancel", "4242"' in (FAKE / "gh.log").read_text(), (FAKE / "gh.log").read_text())
    check("mid-run: its PR was dropped from the line", any(c["pr"] == 110 and c["ok"] for c in calls(ev="drop", case="t10")), calls(ev="drop"))
    check("mid-run: nothing is left: no practice ref, no case folder", practice_refs() == [] and case_dirs("mid1") == [], (practice_refs(), case_dirs("mid1")))
    check("mid-run: the report says stopped, with the unit, and marks the rows", "stopped:" in report("mid1") and "stackshot-release-77.service" in report("mid1") and "INTERRUPTED" in report("mid1") and "PENDING" in report("mid1"), report("mid1"))
    (FAKE / "release_units").unlink(); (FAKE / "hold-t10").unlink()
    adds_t01 = len(calls(ev="add", run="mid1", case="t01"))
    r = tool("run", "--resume", "mid1", "--gate-poll", "0.2", "--driver-wait", "3", "--settle", "0.3", "--salamander", "salamander")
    R3 = rows("mid1")
    check("resume: exit 0 and all three rows match", r.returncode == 0 and all(R3[c][5] == "yes" for c in ("t01", "t10", "t11")), (r.returncode, r.stderr[-800:], R3))
    check("resume: runs only the cases that are not done (t01 was added once in total)", len(calls(ev="add", run="mid1", case="t01")) == adds_t01 == 1 and len(calls(ev="add", run="mid1", case="t10")) == 2
          and len(calls(ev="add", run="mid1", case="t11")) == 1)
    check("resume: nothing left behind", practice_refs() == [] and case_dirs("mid1") == [])
    check("a run id that exists is refused without --resume; one that does not exist cannot be resumed", tool("run", "--run", "mid1", *COMMON).returncode != 0 and tool("run", "--resume", "nope").returncode != 0)

    # ============================================================ a driver still building when the release appears: it pushes its group after the first cancel
    (FAKE / "late-t10").write_text("x")
    canc0 = len((FAKE / "cancel.log").read_text().split()) if (FAKE / "cancel.log").exists() else 0
    gh0 = len((FAKE / "gh.log").read_text().splitlines())
    p = popen("late1", "--profile", "full", "--concurrency", "1", "--cases", "t10")
    grp_file = OUTER_STATE / "stackshot" / "mq-replay" / "late1" / "cases" / "t10" / "state" / "mergequeue" / SLUG.replace("/", "__") / "groups" / "g1.json"
    check("late push: the group is built (phase built, no run yet) when the release appears", wait_for(grp_file.exists, 40) and json.loads(grp_file.read_text())["phase"] == "built", (ROOT / "late1.err").read_text()[-400:])
    (FAKE / "release_units").write_text("stackshot-release-78.service loaded active running release of PR 78\n")
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    (FAKE / "release_units").unlink(); (FAKE / "late-t10").unlink()
    gh_new = [json.loads(x) for x in (FAKE / "gh.log").read_text().splitlines()[gh0:]]
    canc_new = (FAKE / "cancel.log").read_text().split()[canc0:] if (FAKE / "cancel.log").exists() else []
    check("late push: the driver did push the group after the first cancel (and CI started a run for it)", calls(ev="late_pushed", case="t10"), calls(case="t10")[-3:])
    check("late push: the run it started was found by the branch listing after the driver was gone, and cancelled", "4242" in canc_new and any(c[:2] == ["run", "list"] and "queue/practice/late1/t10/g1" in c for c in gh_new), (canc_new, gh_new))
    check("late push: only the replay's own branch was listed (queue/practice/<run>/<case>/...)", all(c[c.index("--branch") + 1].startswith("queue/practice/late1/t10/") for c in gh_new if c[:2] == ["run", "list"] and "--branch" in c))
    check("late push: exit 75, nothing left behind", p.returncode == 75 and practice_refs() == [] and case_dirs("late1") == [], (p.returncode, practice_refs(), case_dirs("late1")))

    # ============================================================ `systemctl stop` / Ctrl-C end the waiting `mq wait` child together with the tool: no verdict, an interruption
    (FAKE / "hold-t10").write_text("x"); (FAKE / "wait-t10.pid").unlink(missing_ok=True)
    canc0 = len((FAKE / "cancel.log").read_text().split())
    p = popen("wsig1", "--profile", "full", "--concurrency", "1", "--cases", "t10,t11")
    check("wait child: the case is in flight and its `mq wait` is running", wait_for(lambda: "refs/heads/queue/practice/wsig1/t10/g1" in practice_refs() and (FAKE / "wait-t10.pid").exists(), 40), (ROOT / "wsig1.err").read_text()[-300:])
    wpid = int((FAKE / "wait-t10.pid").read_text())
    check("wait child: the pid is the test's own fake salamander (checked by its command line before it is signalled)", str(BIN / "salamander").encode() in pathlib.Path(f"/proc/{wpid}/cmdline").read_bytes().split(b"\0"))
    os.kill(wpid, signal.SIGTERM)                            # the child dies first ...
    time.sleep(0.6); term(p)                                 # ... the tool's own SIGTERM comes later
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    st = runjson("wsig1")["cases"]
    canc_new = (FAKE / "cancel.log").read_text().split()[canc0:]
    check("wait child: the tool's own SIGTERM, arriving after the child died, is what the case reports (the handler gets a moment before the wait is called an unexplained signal death)", "SIGTERM" in (st["t10"]["error"] or ""), st["t10"])
    check("wait child: the case is interrupted with no row (not a mismatch), the next case never started, exit 143", p.returncode == 143 and st["t10"]["status"] == "interrupted" and st["t10"]["row"] is None and st["t11"]["status"] == "pending"
          and not [c for c in calls(ev="add") if c["run"] == "wsig1" and c["case"] == "t11"], (p.returncode, {k: (v["status"], v.get("row")) for k, v in st.items()}))
    check("wait child: the interrupted case still cancelled its CI run and left nothing", "4242" in canc_new and practice_refs() == [] and case_dirs("wsig1") == [], (canc_new, practice_refs()))
    (FAKE / "hold-t10").unlink()
    r = tool("run", "--resume", "wsig1", "--gate-poll", "0.2", "--driver-wait", "3", "--settle", "0.3")
    R5 = rows("wsig1")
    check("wait child: the run is resumable, and the resumed run gives both cases a matching row", r.returncode == 0 and R5["t10"][5] == "yes" and R5["t11"][5] == "yes", (r.returncode, r.stderr[-300:], R5))

    # ============================================================ a run GitHub lists a little after the push is still found (one more look after --settle)
    (FAKE / "late-t10").write_text("x"); (FAKE / "run-delay").write_text("0.8")
    canc0 = len((FAKE / "cancel.log").read_text().split()); gh0 = len((FAKE / "gh.log").read_text().splitlines())
    p = popen("late2", "--profile", "full", "--concurrency", "1", "--cases", "t10", "--settle", "4")
    grp_file = OUTER_STATE / "stackshot" / "mq-replay" / "late2" / "cases" / "t10" / "state" / "mergequeue" / SLUG.replace("/", "__") / "groups" / "g1.json"
    wait_for(grp_file.exists, 40)
    (FAKE / "release_units").write_text("stackshot-release-79.service loaded active running release of PR 79\n")
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    (FAKE / "release_units").unlink(); (FAKE / "late-t10").unlink(); (FAKE / "run-delay").unlink()
    gh_new = [json.loads(x) for x in (FAKE / "gh.log").read_text().splitlines()[gh0:]]
    lists = [c for c in gh_new if c[:2] == ["run", "list"] and "queue/practice/late2/t10/g1" in c]
    check("late run: the listing right after the driver left was empty (the run is not listed yet), the second look found it and cancelled it", len(lists) >= 2 and "4242" in (FAKE / "cancel.log").read_text().split()[canc0:], (len(lists), (FAKE / "cancel.log").read_text().split()[canc0:]))
    check("late run: exit 75 and nothing left", p.returncode == 75 and practice_refs() == [] and case_dirs("late2") == [], (p.returncode, practice_refs()))

    # ============================================================ a case that fails in the middle; a driver that leaves its branches
    (FAKE / "fail-t12").write_text("x")
    r = run_tool("fail1", "--profile", "full", "--cases", "t12,t01")
    R4 = report("fail1")
    st = runjson("fail1")["cases"]
    check("mid-run failure: the case is ERROR with the cause, the next case still runs and matches, exit 1", r.returncode == 1 and st["t12"]["status"] == "error" and "mq add exited 1" in (st["t12"]["error"] or "")
          and st["t01"]["status"] == "done" and "| t12 |" in R4 and "ERROR" in R4, (r.returncode, st["t12"], r.stderr[-500:]))
    pl = [ln.split() for ln in POLICY_LOG.read_text().splitlines() if "/fail1/t12" in ln]
    check("mid-run failure: the practice base was pushed before the failure and deleted by the cleanup", any(x[1] == zero for x in pl) and any(x[2] == zero for x in pl) and practice_refs() == [] and case_dirs("fail1") == [], pl)
    (FAKE / "fail-t12").unlink()
    (FAKE / "leave").write_text("x")
    r = run_tool("leave1", "--profile", "full", "--cases", "t07")
    left_ev = calls(ev="driver_left", case="t07")
    check("a driver that leaves its entry branches: both were there when it ended, and the tool's sweep removed them", left_ev and len(left_ev[0]["branches"]) == 2 and practice_refs() == [] and r.returncode == 0, (left_ev, r.stderr[-400:]))
    (FAKE / "leave").unlink()

    # ============================================================ SIGTERM
    (FAKE / "hold-t10").write_text("x"); (FAKE / "stubborn-t10").write_text("x")
    p = popen("term1", "--profile", "full", "--concurrency", "1", "--cases", "t10,t11")
    check("SIGTERM: the case is in flight", wait_for(lambda: "refs/heads/queue/practice/term1/t10/g1" in practice_refs(), 40), (practice_refs(), (ROOT / "term1.err").read_text()[-400:]))
    term(p)
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    st = runjson("term1")["cases"]
    check("SIGTERM: exit 143, the case is interrupted, the next one never started", p.returncode == 143 and st["t10"]["status"] == "interrupted" and st["t11"]["status"] == "pending", (p.returncode, {k: v["status"] for k, v in st.items()}))
    check("SIGTERM: practice refs and case folders are gone, the CI run was cancelled", practice_refs() == [] and case_dirs("term1") == [] and "4242" in (FAKE / "gh.log").read_text())
    check("SIGTERM: a driver that does not leave when its PRs are dropped is stopped by its unit name, not killed",
          "mq-acme-org__stackshot-term1-t10.service" in (FAKE / "stopped.log").read_text(), (FAKE / "stopped.log").read_text() if (FAKE / "stopped.log").exists() else None)
    (FAKE / "hold-t10").unlink(); (FAKE / "stubborn-t10").unlink()

    # ============================================================ --keep, --detach, owner
    r = run_tool("keep1", "--cases", "t01", "--keep")
    kcfg = OUTER_STATE / "stackshot" / "mq-replay" / "keep1" / "cases" / "t01" / "config"
    check("--keep: the kept case folder holds the gh config as a symlink to the real folder, not a copy", (kcfg / "gh").is_symlink() and os.path.realpath(kcfg / "gh") == os.path.realpath(OUTER_CONF / "gh"), os.listdir(kcfg) if kcfg.exists() else None)
    check("--keep keeps the case's folder and clone, the practice branches are deleted all the same", r.returncode == 0 and case_dirs("keep1") == ["t01"] and (OUTER_STATE / "stackshot" / "mq-replay" / "keep1" / "cases" / "t01" / "clone" / ".git").exists()
          and practice_refs() == [], (r.returncode, case_dirs("keep1"), r.stderr[-300:]))
    r = tool("run", "--detach", "--run", "det1", "--cases", "t01", "--profile", "full", *COMMON, env={"GH_CONFIG_DIR": str(OUTER_CONF / "gh"), "GH_TOKEN": "tok-not-real-0000"})
    sr = [json.loads(x) for x in (FAKE / "systemd_run.log").read_text().splitlines()]
    cmd = sr[-1] if sr else []
    check("--detach starts the transient unit stackshot-mq-replay-<run> with systemd-run --user and returns", r.returncode == 0 and "stackshot-mq-replay-det1" in r.stdout and "--user" in cmd and cmd[cmd.index("--unit") + 1] == "stackshot-mq-replay-det1", (r.returncode, r.stdout, cmd))
    check("--detach forwards GH_CONFIG_DIR (a folder) into the unit and never a token: no GH_TOKEN in the unit's environment or the command line",
          f"--setenv=GH_CONFIG_DIR={OUTER_CONF / 'gh'}" in cmd and not any("GH_TOKEN" in x or "GITHUB_TOKEN" in x or "tok-not-real" in x for x in cmd), cmd)
    check("--detach gives the unit a stop timeout longer than the cleanup's waits (TimeoutStopSec=300) and passes the instance config (the release folder comes from it)",
          "TimeoutStopSec=300" in cmd and f"--setenv=STACKSHOT_CONFIG={INSTANCE_CONFIG}" in cmd, cmd)
    check("--detach runs the same command in the unit without --detach, and starts nothing itself", "--detach" not in cmd and cmd[cmd.index("--") + 2:][-0:] and "run" in cmd and cmd[cmd.index("run") + 1:cmd.index("run") + 3] == ["--run", "det1"] and practice_refs() == []
          and not (OUTER_STATE / "stackshot" / "mq-replay" / "det1" / "run.json").exists(), cmd)
    r = tool("run", "--detach", "--cases", "t01", *COMMON)
    sr = [json.loads(x) for x in (FAKE / "systemd_run.log").read_text().splitlines()]
    check("--detach without --run makes the id once and passes it on", r.returncode == 0 and re.search(r"stackshot-mq-replay-(\d{8}T\d{6}Z)", r.stdout) and "--run" in sr[-1] and sr[-1][sr[-1].index("--run") + 1] in r.stdout, (r.stdout, sr[-1]))
    (FAKE / "systemd_run_fail").write_text("x"); r = tool("run", "--detach", "--run", "det2", *COMMON); (FAKE / "systemd_run_fail").unlink()
    check("--detach says so when systemd-run fails", r.returncode == 1 and "could not start" in r.stderr, r.stderr)
    r = tool("run", "--run", "own1", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--cases-file", str(CASES_FILE), "--cases", "t01")
    check("an owner that cannot be derived fails clearly before anything is pushed", r.returncode != 0 and "--slug" in r.stderr and "owner" in r.stderr and practice_refs() == [], (r.returncode, r.stderr))
    r = tool("run", "--run", "own2", "--repo", str(WC), "--remote", "git@github.com:acme-org/widgets.git", "--cases-file", str(CASES_FILE), "--cases", "nope", "--gate-poll", "0.2")
    check("a github.com remote gives the owner and name; an unknown case is refused", r.returncode != 0 and "no such case: nope" in r.stderr, r.stderr)
    r = tool("run", "--run", "../evil", *COMMON)
    check("a run id that is not a plain name is refused", r.returncode != 0 and "run id" in r.stderr and practice_refs() == [], r.stderr)

    # ============================================================ report
    r = tool("report", "--run", "b1")
    check("report prints the table of a run", r.returncode == 0 and "| t04 |" in r.stdout and r.stdout == report("b1"))
    r = tool("report")
    check("report with no run takes the newest", r.returncode == 0 and r.stdout.startswith("# mq replay"), r.stderr)
    check("report of a run that is not there is an error", tool("report", "--run", "zzz").returncode == 2)

    # ============================================================ clean
    (FAKE / "hold-t10").write_text("x")
    p = popen("live1", "--profile", "full", "--concurrency", "1", "--cases", "t10")
    live_refs = ["refs/heads/practice/live1/t10", "refs/heads/queue/practice/live1/t10/g1"]
    check("clean vs a live run: the run is in flight (its practice base and group branch are on origin)", wait_for(lambda: all(x in practice_refs() for x in live_refs), 40), (practice_refs(), (ROOT / "live1.err").read_text()[-300:]))
    time.sleep(1.2)
    r = tool("clean", "--older-than", "1s", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG)
    check("clean --older-than does not touch a run that holds its lock, however old: its branches stay, it says so", r.returncode == 0 and all(x in practice_refs() for x in live_refs) and "run live1 is running" in r.stdout and p.poll() is None,
          (r.returncode, r.stdout, r.stderr, practice_refs()))
    r = tool("clean", "--run", "live1", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG)
    check("clean --run on a live run leaves it alone too, and exits 1 so the caller sees it", r.returncode == 1 and all(x in practice_refs() for x in live_refs) and "is running" in r.stdout and case_dirs("live1") == ["t10"], (r.returncode, r.stdout))
    (FAKE / "hold-t10").unlink()
    try: p.wait(60)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
    check("clean vs a live run: the run was not disturbed, it finishes with a matching row and leaves nothing", p.returncode == 0 and rows("live1")["t10"][5] == "yes" and practice_refs() == [], (p.returncode, (ROOT / "live1.err").read_text()[-300:]))

    ux, ux2 = "mq-acme-org__stackshot-cl1-c01.service", "mq-acme-org__stackshot-cl10-c01.service"
    procs_ = []
    for u_ in (ux, ux2):
        pr_ = subprocess.Popen([sys.executable, "-c", f"import os,time\nend=time.time()+120\nwhile not os.path.exists({str(FAKE / ('stop-' + u_))!r}) and time.time()<end: time.sleep(0.05)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); procs_.append(pr_)      # a fake unit's process: ends on its stop marker, or by itself after 2 minutes
        (FAKE / "units" / (u_ + ".pid")).write_text(str(pr_.pid))
    for ref in ("refs/heads/practice/cl1/c01", "refs/heads/queue/practice/cl1/c01/g1", "refs/heads/practice/cl10/c01"): g(ORIGIN, "update-ref", ref, B)
    r = tool("clean", "--run", "cl1", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG, "--dry-run")
    stopped_ = (FAKE / "stopped.log").read_text() if (FAKE / "stopped.log").exists() else ""
    check("clean --dry-run names the driver unit it would stop and stops nothing", f"would stop {ux}" in r.stdout and procs_[0].poll() is None and ux not in stopped_, r.stdout)
    r = tool("clean", "--run", "cl1", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG)
    try: procs_[0].wait(10)
    except subprocess.TimeoutExpired: pass
    check("clean --run stops the leftover driver units of that run (mq-<owner>__<repo>-<run>-<case>) before the refs go, and only that run's", r.returncode == 0 and f"stop {ux}" in r.stdout and procs_[0].poll() is not None
          and ux in (FAKE / "stopped.log").read_text() and ux2 not in (FAKE / "stopped.log").read_text() and procs_[1].poll() is None, (r.stdout, r.stderr))
    check("clean --run cl1 deleted its refs and left run cl10's", "refs/heads/practice/cl1/c01" not in origin_refs() and "refs/heads/queue/practice/cl1/c01/g1" not in origin_refs() and "refs/heads/practice/cl10/c01" in origin_refs())
    ua, uab = "mq-acme-org__stackshot-a-c01.service", "mq-acme-org__stackshot-a-b-c01.service"          # run `a` case c01, and run `a-b` case c01 (run `a` with a case `b-c01` would be the same name)
    for u_ in (ua, uab):
        pr_ = subprocess.Popen([sys.executable, "-c", f"import os,time\nend=time.time()+120\nwhile not os.path.exists({str(FAKE / ('stop-' + u_))!r}) and time.time()<end: time.sleep(0.05)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); procs_.append(pr_)
        (FAKE / "units" / (u_ + ".pid")).write_text(str(pr_.pid))
    for ref in ("refs/heads/practice/a/c01", "refs/heads/practice/a-b/c01"): g(ORIGIN, "update-ref", ref, B)
    r = tool("clean", "--run", "a", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--slug", SLUG)
    stopped_ = (FAKE / "stopped.log").read_text()
    try: procs_[-2].wait(10)
    except subprocess.TimeoutExpired: pass
    check("clean --run a stops the unit of run a's case, by its exact name, and not the live driver of run a-b", r.returncode == 0 and f"stop {ua}" in r.stdout and ua in stopped_ and uab not in stopped_ and procs_[-1].poll() is None
          and procs_[-2].poll() is not None, (r.stdout, r.stderr, stopped_))
    check("clean --run a left run a-b's branch", "refs/heads/practice/a-b/c01" in origin_refs() and "refs/heads/practice/a/c01" not in origin_refs())
    g(ORIGIN, "update-ref", "-d", "refs/heads/practice/a-b/c01")
    (FAKE / ("stop-" + uab)).write_text("x"); procs_[-1].wait(10)
    g(ORIGIN, "update-ref", "-d", "refs/heads/practice/cl10/c01")
    (FAKE / ("stop-" + ux2)).write_text("x"); procs_[1].wait(10)

    def mkref(ref, sha=B): g(ORIGIN, "update-ref", ref, sha)
    now_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    keep = ["refs/heads/feat/practice/del1/c01", "refs/heads/practice-old/del1", "refs/heads/queue/main/g9", "refs/heads/practice/keep1x/c01", f"refs/heads/practice/{now_id}/c01", "refs/heads/practice/mystery/c01"]
    drop = ["refs/heads/practice/del1/c01", "refs/heads/practice/del1/c02", "refs/heads/queue/practice/del1/c01/g1", "refs/heads/queue/practice/del1/c01/g2"]
    for ref in keep + drop: mkref(ref)
    r = tool("clean", "--run", "del1", "--repo", str(WC), "--remote", f"file://{ORIGIN}", "--dry-run")
    check("clean --dry-run lists and deletes nothing", r.returncode == 0 and all(d in r.stdout for d in drop) and all(x in origin_refs() for x in drop), r.stdout)
    r = tool("clean", "--run", "del1", "--repo", str(WC), "--remote", f"file://{ORIGIN}")
    after = origin_refs()
    check("clean --run deletes that run's practice and queue/practice refs only", r.returncode == 0 and not any(d in after for d in drop) and all(k in after for k in keep), (r.stdout, r.stderr))
    r = tool("clean", "--run", "main", "--repo", str(WC), "--remote", f"file://{ORIGIN}")
    check("clean --run main deletes nothing (main is not a run's ref)", r.returncode == 0 and "0 ref(s)" in r.stdout and g(ORIGIN, "rev-parse", "refs/heads/main") == MAIN_BEFORE, r.stdout)
    old_refs = ["refs/heads/practice/20200101T000000Z/c01", "refs/heads/queue/practice/20200101T000000Z/c01/g1"]
    for ref in old_refs: mkref(ref)
    r = tool("clean", "--older-than", "1d", "--repo", str(WC), "--remote", f"file://{ORIGIN}")
    after = origin_refs()
    check("clean --older-than deletes an old run's refs, keeps a fresh run's, and leaves one whose age is unknown (named)", r.returncode == 0 and not any(o in after for o in old_refs) and f"refs/heads/practice/{now_id}/c01" in after
          and "refs/heads/practice/mystery/c01" in after and "mystery" in r.stdout, (r.stdout, r.stderr))
    check("clean touched no ref but the practice ones; main and the PR refs are as they were", g(ORIGIN, "rev-parse", "refs/heads/main") == MAIN_BEFORE and all(f"refs/pull/{n}/head" in after for n in H))
    check("clean: a bad age is a usage error", tool("clean", "--older-than", "soon", "--repo", str(WC), "--remote", f"file://{ORIGIN}").returncode != 0 and tool("clean", "--repo", str(WC), "--remote", f"file://{ORIGIN}").returncode != 0)
    for ref in keep + drop + old_refs:
        if ref in origin_refs(): g(ORIGIN, "update-ref", "-d", ref)
    r = tool("clean", "--run", "keep1", "--repo", str(WC), "--remote", f"file://{ORIGIN}")
    check("clean --run removes a kept run's case folders; the links in them go as links and the real gh config stays whole", r.returncode == 0 and case_dirs("keep1") == [] and tree_hash(OUTER_CONF / "gh") == GH_HASH
          and (OUTER_STATE / "salamander" / "ci-runs" / "x.json").is_file(), (r.stdout, case_dirs("keep1")))
    check("isolation (end): the decoy folder is still byte-identical and origin carries only what it started with", tree_hash(DECOY) == DECOY_HASH and origin_refs() == REFS_BEFORE)
    check("the tool left no scratch folder or leftover clone in the run folders", not list((OUTER_STATE / "stackshot" / "mq-replay").glob(".clean-push-*")) and not list((OUTER_STATE / "stackshot" / "mq-replay").glob("*/push.git")))
finally:
    for u in (FAKE / "units").glob("*.pid"):          # a fake driver still alive ends itself on its stop marker (nothing is killed)
        (FAKE / ("stop-" + u.name.removesuffix(".pid"))).write_text("x")
    for h_ in FAKE.glob("hold-*"): h_.unlink()
    for pr_ in globals().get("procs_", []):           # the fake unit processes of the clean test end on their markers; reaped here
        try: pr_.wait(10)
        except subprocess.TimeoutExpired: pass

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
