"""Scenario test for the publisher's server host check: `publish`, `bump` and `flush` render the board from the box's own copy of the store, commit it and
push it, so only the server host runs them. Fixture data only: each case has a bare repository acting as the mirror, a store clone behind it with a file
of its own to commit, and its own state, secrets and HOME, all in scratch folders from tests/_scratch.py; no network; the other hosts' names are made up.

Covers: refused where [release] deploy_ssh names another box (a plain name, a host word that resolves to another box, one that does not resolve, beside
[server] box = true) and where [server] box = false names no host: exit 1, one line that names the server (or the address the client reaches it at,
without a user, a password or a path) and the command to run there, and not one file of the instance changed, the clone's .git and the mirror included
(nothing fetched, written, committed or pushed), through `stackshot publish ...` and `publish.py ...`. Allowed, as without the check: a config that names
no server host, deploy_ssh naming this box (hostname, short name, user@, localhost, a host word, beside box = false), box = true, and a check that
cannot run. The shape of a script's call over ssh (an environment of HOME and STACKSHOT_CONFIG alone, the config a ~ path that is a symlink). In the
server process: publish() raises, the debounced publish says so once an hour and writes nothing. A standby refuses in its own words. brief and render run
on a refused box and write nothing.

    tests/run-suite publish_host       -> exit 0 / 1"""
import contextlib, hashlib, io, json, logging, os, pathlib, re, socket, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
T = pathlib.Path(_scratch.mkdtemp(prefix="pubhost-"))
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_READ_ONLY", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
os.environ.update(GIT_ENV)
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

ME = socket.gethostname()
OTHER = "board-host.invalid"
CLIENT_URL = "https://stackshot.example.com"          # the example config's [client] url
NOTHING = "Nothing was fetched, written, committed or pushed; "

def git(cwd, *a) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()
def write(path, text): path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8")
def commit(repo, msg, **files):
    for name, text in files.items(): write(repo / name, text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg)
def patch(text, old, new):
    text, n = re.subn(old, lambda m: new, text); assert n == 1, (old, n)
    return text

def config_text(w, deploy_ssh="", box=None, lookup="", client_url=CLIENT_URL):
    toml = _instance.apply(_instance.base_toml())
    assert 'session_links = ""' in toml          # no other tool's files are read
    for key, val in (("repo", f"{w}/repo"), ("store", f"{w}/repo/board-data"), ("markdown", f"{w}/repo/board.md"), ("brain", f"{w}/brain"), ("fleet_names", f"{w}/names.tsv"),
                     ("state", f"{w}/state"), ("secrets", f"{w}/secrets"), ("project_touch", f"{w}/touch"), ("rules", f"{w}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml = patch(toml, rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"')
    # no version lookup and no package command: the publisher asks nothing outside the case
    toml, n = re.subn(r"(?ms)^\[\[machines_panel\.packages\]\].*?(?=^\[)", "", toml); assert n >= 1
    toml = patch(toml, r"(?m)^latest_lookups = true", "latest_lookups = false")
    toml = patch(toml, r'(?m)^deploy_ssh = ""', f'deploy_ssh = "{deploy_ssh}"')
    toml = patch(toml, rf'(?m)^url = "{re.escape(CLIENT_URL)}"', f'url = "{client_url}"')
    if box is not None: toml = patch(toml, r"(?m)^\[server\][^\n]*", f"[server]\nbox = {'true' if box else 'false'}")
    if lookup: toml += f'\n[hosts]\nlookup = "{lookup}"\n'
    return toml

def world(name, **settings):
    """A case's instance: the mirror, the store clone (one commit behind the mirror, with an item file of its own not yet committed), another writer's push,
    a brain with one page, state, secrets, HOME and the config."""
    w = T / name; w.mkdir()
    git(w, "init", "-q", "--bare", "-b", "main", str(w / "origin.git")); git(w, "clone", "-q", str(w / "origin.git"), str(w / "repo"))
    commit(w / "repo", "first", **{"board.md": "board\n", "board-data/README": "data\n"}); git(w / "repo", "branch", "-M", "main"); git(w / "repo", "push", "-q", "-u", "origin", "main")
    git(w, "clone", "-q", str(w / "origin.git"), str(w / "other")); commit(w / "other", "elsewhere", **{"elsewhere.txt": "from another writer\n"}); git(w / "other", "push", "-q", "origin", "main")
    write(w / "repo/board-data/projects.json", json.dumps({"pages": {"projects/local-copy": {"title": "Local", "name": "Local", "status": "active", "agents": {"local-main": "m"}}}}))
    write(w / "brain/projects/alpha.md", "---\ntitle: Alpha\nname: Alpha\n---\n\n# Alpha\n")
    for d in ("state", "secrets", "touch", "home"): (w / d).mkdir()
    write(w / "stackshot.toml", config_text(w, **settings))
    return w

def snapshot(w):
    """Every file of a case with its content and its time, the clone's .git and the mirror included."""
    out = {}
    for p in sorted(w.rglob("*")):
        rel = str(p.relative_to(w))
        out[rel] = (p.lstat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) if p.is_file() and not p.is_symlink() else ("not a file",)
    return out
def changed(before, after): return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))

def env_of(w, **extra):
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(w / "home"), "STACKSHOT_CONFIG": str(w / "stackshot.toml"), "PYTHONDONTWRITEBYTECODE": "1", **GIT_ENV, **extra}
def python(w, argv, env=None):
    return subprocess.run([sys.executable, *argv], capture_output=True, text=True, env=env or env_of(w), cwd=STACK, timeout=300)
def cli(w, *words, env=None): return python(w, [os.path.join(STACK, "bin/stackshot"), "publish", *words], env)
def script(w, *words): return python(w, [os.path.join(STACK, "stackshot/web/publish.py"), *words])

def published(w):
    """The publisher went through: the mirror's commit was taken in, the store's own file committed, and the mirror holds the store's head."""
    return (git(w / "origin.git", "rev-parse", "main") == git(w / "repo", "rev-parse", "HEAD") and (w / "repo/elsewhere.txt").is_file()
            and git(w / "repo", "log", "-1", "--format=%s").startswith("board: ") and "board-data/projects.json" in git(w / "origin.git", "ls-tree", "-r", "--name-only", "main"))

def refused(name, r, w, before, *says, absent=()):
    lines = r.stderr.strip().splitlines()
    check(f"{name}: exit 1, nothing on stdout, no traceback", r.returncode == 1 and r.stdout == "" and "Traceback" not in r.stderr, (r.returncode, r.stdout[-300:], r.stderr[-900:]))
    check(f"{name}: one line, naming this box and saying nothing was done", len(lines) == 1 and lines[0].startswith(f"publish: refused on {ME}, which is not the server host: ") and NOTHING in lines[0], r.stderr[-900:])
    for s in says: check(f"{name}: the line says {s!r}", s in r.stderr, r.stderr[-900:])
    for s in absent: check(f"{name}: the line does not say {s!r}", s not in r.stderr, r.stderr[-900:])
    check(f"{name}: not one file of the instance changed", changed(before, snapshot(w)) == [], changed(before, snapshot(w))[:20])


# ============================================================= 1. refused: deploy_ssh names another box
w = world("other", deploy_ssh=OTHER); before = snapshot(w)
for words in (("publish",), ("bump",), ("flush",), ("bump", "--host", "box-b"), ()):
    shown = " ".join(words or ("publish",))
    refused(f"other box, stackshot publish {shown}", cli(w, *words), w, before, f"[release] deploy_ssh says the server runs on {OTHER}",
            f"run it there: `ssh {OTHER} '~/stackshot/bin/stackshot publish {shown}'`", absent=("the server answers at",))
for words in (("publish",), ("bump",), ("flush",), ()):
    shown = " ".join(words or ("publish",))
    refused(f"other box, publish.py {shown}", script(w, *words), w, before, f"`ssh {OTHER} '~/stackshot/bin/stackshot publish {shown}'`")
r = cli(w, "nonsense")
check("other box: an unknown word still gets the usage, which says where publish, flush and bump run", r.returncode == 1 and r.stderr.startswith("usage: publish.py ") and "on the server host only" in r.stderr, r.stderr[-400:])

# ---- brief and render stay allowed there, and write nothing
for words, head in ((("brief",), "Board: "), (("render",), "# "), (("render", "brief"), "Board: ")):
    r = cli(w, *words)
    check(f"other box: {' '.join(words)} runs", r.returncode == 0 and r.stdout.startswith(head) and "refused" not in r.stderr, (r.returncode, r.stdout[:200], r.stderr[-600:]))
    check(f"other box: {' '.join(words)} wrote nothing", changed(before, snapshot(w)) == [], changed(before, snapshot(w))[:20])

# ---- a standby copy there refuses in its own words, not with the host line
before = snapshot(w)
r = cli(w, "publish", env=env_of(w, STACKSHOT_READ_ONLY="1"))
check("a standby on another box: the standby's refusal, as before", r.returncode != 0 and "read-only standby" in r.stderr and "not the server host" not in r.stderr, (r.returncode, r.stderr[-600:]))
check("a standby on another box wrote nothing", changed(before, snapshot(w)) == [], changed(before, snapshot(w))[:20])

# ============================================================= 2. the other refusals
for name, settings, says, absent in (
        ("box-true", {"deploy_ssh": OTHER, "box": True}, (f"the server runs on {OTHER}", f"`ssh {OTHER} '~/stackshot/bin/stackshot publish bump'`"), ()),
        ("user-at", {"deploy_ssh": f"deploy@{OTHER}"}, (f"`ssh deploy@{OTHER} '~/stackshot/bin/stackshot publish bump'`",), ()),
        ("word-other", {"deploy_ssh": f"host:{OTHER}", "lookup": "/bin/echo {role}"}, (f"the server runs on {OTHER} ", f"`ssh {OTHER} '~/stackshot/bin/stackshot publish bump'`"), (f"host:{OTHER}",)),
        ("word-unresolved", {"deploy_ssh": "host:board"}, ("the host word host:board and its [hosts] lookup did not resolve", f"the server answers at {CLIENT_URL}.",
                                                           "run it on the server host: `~/stackshot/bin/stackshot publish bump`"), ("`ssh ",)),
        ("box-false", {"box": False}, ("[server] box = false says the server runs on another box", f"; the server answers at {CLIENT_URL}. ",
                                       "run it on the server host: `~/stackshot/bin/stackshot publish bump`"), ("`ssh ",)),
        ("box-false-userinfo", {"box": False, "client_url": "https://someone:hunter2@board.invalid:8443/private/path?k=v"}, ("the server answers at https://board.invalid:8443. ",),
         ("someone", "hunter2", "private", "k=v")),
        ("box-false-loopback", {"box": False, "client_url": "http://127.0.0.1:8787"}, ("run it on the server host: ",), ("the server answers at", "127.0.0.1"))):
    w = world(name, **settings); before = snapshot(w)
    refused(name, cli(w, "bump"), w, before, *says, absent=absent)
w = world("saved-address", box=False); write(w / "secrets/client.url", "http://saved.invalid:9000/\n"); before = snapshot(w)
refused("the address saved on this box wins over [client] url", cli(w, "publish"), w, before, "the server answers at http://saved.invalid:9000. ", absent=(CLIENT_URL,))

# ============================================================= 3. allowed: as without the check
for name, settings, words in (
        ("unset", {}, ("publish",)),
        ("own-name", {"deploy_ssh": ME}, ("bump",)),
        ("own-short-name", {"deploy_ssh": ME.split(".")[0]}, ("flush",)),
        ("own-user-at", {"deploy_ssh": f"deploy@{ME}"}, ("publish",)),
        ("localhost", {"deploy_ssh": "localhost"}, ("publish",)),
        ("own-word", {"deploy_ssh": f"host:{ME}", "lookup": "/bin/echo {role}"}, ("bump",)),
        ("box-set", {"box": True}, ("flush",)),
        ("own-name-box-false", {"deploy_ssh": ME, "box": False}, ("publish",))):
    w = world(name, **settings); r = cli(w, *words)
    check(f"allowed ({name}): {words[0]} exits 0, commits and pushes", r.returncode == 0 and "not the server host" not in r.stderr and published(w), (r.returncode, r.stdout[-300:], r.stderr[-900:]))
w = world("script-form", deploy_ssh=ME); r = script(w, "flush")
check("allowed: publish.py flush (the reboot hook's step) commits and pushes", r.returncode == 0 and "committed and pushed" in r.stdout and published(w), (r.returncode, r.stdout[-300:], r.stderr[-900:]))

# ---- a script's call over ssh: a non-login shell that has HOME and STACKSHOT_CONFIG and nothing of a user session; the config a ~ path that is a symlink
def over_ssh(name, deploy_ssh):
    w = world(name, deploy_ssh=deploy_ssh)
    (w / "shared").mkdir(); (w / "stackshot.toml").rename(w / "shared/stackshot.toml")
    write(w / "home/.gitconfig", "[user]\n\tname = t\n\temail = t@x\n")          # the fixture account's identity: the call carries none in its environment
    (w / "home/.config/stackshot").mkdir(parents=True); (w / "home/.config/stackshot/stackshot.toml").symlink_to(w / "shared/stackshot.toml")
    return w, {"HOME": str(w / "home"), "STACKSHOT_CONFIG": "~/.config/stackshot/stackshot.toml"}
w, env = over_ssh("ssh-server", ME); r = cli(w, "bump", env=env)
check("over ssh on the server host (HOME and STACKSHOT_CONFIG alone): bump exits 0, commits and pushes", r.returncode == 0 and "not the server host" not in r.stderr and published(w), (r.returncode, r.stdout[-300:], r.stderr[-900:]))
w, env = over_ssh("ssh-client", OTHER); before = snapshot(w)
refused("the same call on a box that is not the server host", cli(w, "bump", env=env), w, before, f"`ssh {OTHER} '~/stackshot/bin/stackshot publish bump'`")

# ============================================================= 4. in the process that imports the publisher (the server, deploy tools)
w = world("in-process", deploy_ssh=OTHER)
os.environ.update(STACKSHOT_CONFIG=str(w / "stackshot.toml"), STACKSHOT_AUTH="off", HOME=str(w / "home"))
from stackshot.core import config as cfg
from stackshot.fleet import client
from stackshot.web import publish as P
before = snapshot(w)
for name, call in (("publish()", lambda: P.publish()), ("bump()", lambda: P.bump("box-b"))):
    try: call(); got = None
    except P.NotServerHost as e: got = str(e)
    word = name[:-2]
    check(f"{name} raises NotServerHost with the line", bool(got) and f"`ssh {OTHER} '~/stackshot/bin/stackshot publish {word}'`" in got and "\n" not in got, got)
P._NOTED.clear(); err = io.StringIO()
with contextlib.redirect_stderr(err): first, second = P._publish_now(), P._publish_now(force_versions=True)
check("_publish_now returns the refusal instead of raising", first.startswith("(publish: refused on ") and "publish publish'" in first and "publish bump'" in second and second.endswith(")"), (first, second))
check("_publish_now logs the refusal once, not at every publish", err.getvalue().count("publish: refused on ") == 1 and len(err.getvalue().splitlines()) == 1, err.getvalue())
check("a refused publish in the process wrote nothing, roles.json included", changed(before, snapshot(w)) == [], changed(before, snapshot(w))[:20])

# ---- the address asked of the client
def address(url):
    os.environ["STACKSHOT_URL"] = url
    try: return P._server_address()
    finally: os.environ.pop("STACKSHOT_URL")
for url, want in (("https://someone:hunter2@board.invalid:8443/private?k=v", "https://board.invalid:8443"), ("https://board.invalid", "https://board.invalid"),
                  ("http://[2001:db8::7]:80/x", "http://[2001:db8::7]:80"), ("http://localhost:8787", ""), ("http://127.0.0.1:8787", ""), (f"http://{ME}:8787", ""),
                  ("ftp://board.invalid", ""), ("board.invalid:8787", ""), ("https://board.invalid:port", "")):
    got = address(url)
    check(f"address of {url!r} is {want!r}", got == want, got)
real_url = client.server_url
def broken(*a, **k): raise RuntimeError("no address")
client.server_url = broken
try: check("an address that cannot be read is no address", P._server_address() == "", P._server_address())
finally: client.server_url = real_url
asked = []
line = cfg.publish_host_refusal(["publish"], lambda: asked.append(1) or "https://board.invalid")
check("a refusal that names the host does not ask for an address", line.startswith("publish: refused on ") and asked == [] and "answers at" not in line, (line, asked))
line = cfg.publish_host_refusal(["bump", "--host", "two words"], cfg={"release": {}, "server": {"box": False}})
check("the words are quoted as the shell needs them, and no address is none", "run it on the server host: `~/stackshot/bin/stackshot publish bump --host 'two words'`" in line and "answers at" not in line, line)

# ---- a check that cannot run refuses nothing
real = cfg._server_host_decision
cfg._server_host_decision = broken
try:
    check("a check that cannot run gives no refusal", cfg.publish_host_refusal(["publish"]) == "", cfg.publish_host_refusal(["publish"]))
    got = P.publish()
    check("...and publish() goes through", published(w), got)
finally: cfg._server_host_decision = real

# ---- the server host: the debounced publish as before
w2 = T / "in-process"
git(w2 / "other", "pull", "-q", "--ff-only", "origin", "main"); commit(w2 / "other", "more", **{"more.txt": "x\n"}); git(w2 / "other", "push", "-q", "origin", "main")
write(w2 / "repo/board-data/own.txt", "the store's own\n"); (w2 / "state/roles.json").unlink(missing_ok=True)
cfg.CFG["release"]["deploy_ssh"] = ME
got = P._publish_now()
check("on the server host _publish_now publishes, pushes and writes roles.json", not got.startswith("(") and (w2 / "repo/more.txt").is_file() and (w2 / "state/roles.json").is_file()
      and git(w2 / "origin.git", "rev-parse", "main") == git(w2 / "repo", "rev-parse", "HEAD"), got)

print(("ok" if not fails else "FAILED") + f": publish_host scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
