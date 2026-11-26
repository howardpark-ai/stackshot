"""Scenario test for `stackshot standby-copy` (stackshot/tools/standby_copy.py, docs/standby-copy.md): a scratch instance of made-up files, real OS processes, no server, no network.

  1  the command    listed under `stackshot`, its help needs no config
  2  the stream     every file of the three folders and nothing else (each exclusion on its own file), private modes, no user names, the manifest last and true (hashes, next id, the board's head), a received tree verifies;
                    nothing a file holds is printed, and the sources are left as they were
  3  --out          the same tree in a directory, made beside it and renamed whole; a directory that holds something, or lies inside a source, is refused
  4  --verify       a changed, missing or extra file or directory, a link in a file's place, a missing, cut or malformed manifest and a path that climbs out all exit 1; it needs no config
  5  refusals       not the server box (deploy_ssh names another, [server] box = false), a read-only standby, the cross-process locks off, a terminal for the stream; a missing folder or runtime directory fails
  6  the locks      every lock the package makes is one the command takes, in the order of core/xlock.py; each one held by another process fails the run in its time, naming it, with nothing written and the others free;
                    a short hold is waited out; a holder that takes two locks the other way round is let through
  7  concurrency    a writer saves under the locks, hands out item ids and appends to a log all the while: every copy is one moment of it (the control: an unlocked read of the same files is not)
  8  between        what changes between the first copy and the locks is in the copy: lines added to a log, a log rewritten or replaced, a file changed with the same size and time, files added and removed, a folder for a file
  9  failure        a write error in the staging directory, in the stream (a full device, a reader that leaves) and in --out; a folder that never settles; a file that goes mid-copy; the longest hold; every signal while a lock
                    is waited for, while the locks are held and while the output is blocked: non-zero, no staging directory, no lock held, nothing partial taken for good; a killed run's leftover is removed by a later one
  10 extra          --extra and [standby_copy] extra_dirs, copied with the locks free, until two scans match; one that never settles, is not there or overlaps a source fails

    tests/run-suite standby_copy        -> exit 0 / 1"""
import ast, errno, fcntl, hashlib, io, json, os, pathlib, pty, re, resource, shutil, signal, subprocess, sys, tarfile, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance

CHILD = len(sys.argv) > 1 and sys.argv[1] == "child"
T = pathlib.Path(os.environ["COPY_TEST_TMP"] if CHILD else _scratch.mkdtemp(prefix="standbycopytest-"))
STATE, REPO, SECRETS, RUN = T / "state", T / "repo", T / "secrets", T / "run"
STORE = REPO / "board-data"


# ---------------------------------------------------------------------------- the child processes
def hold_then(tag):
    (T / f"held-{tag}").write_text("1")


def child_writer():
    """Saves the way the server does: two items and the For you list in one hold of the item lock, a log line written inside it, new item ids handed out with no item lock, and a file no lock covers."""
    from stackshot.core import store, xlock
    item, foryou = xlock.XLock("item"), xlock.XLock("for-you")
    g = 0
    while not (T / "writer-stop").exists():
        g += 1
        with item:
            store._write_item(STORE / "a/1.json", {"g": g})
            time.sleep(0.002)
            store._write_item(STORE / "a/2.json", {"g": g, "pad": "x" * (g % 700)})
            with foryou:
                tmp = STATE / "for-you.json.tmp"; tmp.write_text(json.dumps({"g": g})); os.replace(tmp, STATE / "for-you.json")
                time.sleep(0.001)
            with open(STATE / "writer.jsonl", "a", encoding="ascii") as f:
                f.write(json.dumps({"g": g, "pad": "y" * 200}) + "\n")
        if g % 3 == 0:
            nid = store._next_id()
            store._write_item(STORE / "a" / f"{nid[1:]}.json", {"new": nid})
        if g % 25 == 0:
            tmp = STATE / "beat.json.tmp"; tmp.write_text(str(g)); os.replace(tmp, STATE / "beat.json")
        (T / "writer-g").write_text(str(g))
        time.sleep(0.006)


def child_inverse():
    """Takes the item lock, then the project record's: the other way round from the command."""
    from stackshot.core import xlock
    from stackshot.projects import projects
    with xlock.XLock("item"):
        hold_then("inverse")
        time.sleep(1.0)
        with projects.locked():
            (T / "inverse-done").write_text("1")


def child_record():
    from stackshot.projects import projects
    with projects.locked():
        hold_then("record")
        time.sleep(60)


def child_hooked(hook, argv):
    """`stackshot standby-copy` with one function of the module wrapped, to make an event happen at one exact point."""
    from stackshot.tools import standby_copy as s
    real_copy, real_sync, real_held = s.copy_file, s.sync, s.held_locks
    seen = {"n": 0}

    def lock_free(name):
        return free(STATE / f"{name}.lock")

    if hook == "between":                     # after the first copy, before the locks
        s.LOG_WHOLE_BELOW, s.TAIL = 64, 32

        def held(*a, **k):
            with open(STATE / "big.jsonl", "a", encoding="ascii") as f: f.write('{"late": 1}\n{"half": ')
            with open(STATE / "rewritten.log", "r+", encoding="ascii") as f: f.write("R" * 400 + "\n"); f.truncate()
            new = STATE / "rotated.log.new"; new.write_text("fresh\n"); os.replace(new, STATE / "rotated.log")
            p = STATE / "same.json"; st = p.stat(); p.write_text("BBBB"); os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
            (STATE / "gone.json").unlink(); (STATE / "added.json").write_text("added")
            shutil.rmtree(STATE / "was-dir"); (STATE / "was-dir").write_text("now a file")
            (STATE / "was-file").unlink(); (STATE / "was-file").mkdir(); (STATE / "was-file/in.json").write_text("inside")
            (STORE / "next-id").write_text("77")
            return real_held(*a, **k)
        s.held_locks = held
    elif hook == "smalllog":
        s.LOG_WHOLE_BELOW, s.TAIL = 64, 32
    elif hook == "vanish":                    # a file goes just as the pass under the locks reads it
        def copy(src, dst, **k):
            if k["locked"] and src.endswith("vanishing.json") and os.path.exists(src):
                os.remove(src)
            return real_copy(src, dst, **k)
        s.copy_file = copy

        def held(*a, **k):
            (STATE / "vanishing.json").write_text("changed, so that it is read again under the locks")
            return real_held(*a, **k)
        s.held_locks = held
    elif hook == "unsettled":                 # a file is written before every pass under the locks
        def sync(tree, **k):
            if k["locked"] and tree.name == "state":
                seen["n"] += 1; (STATE / "busy.json").write_text("n" * seen["n"])
            return real_sync(tree, **k)
        s.sync = sync
    elif hook in ("slowlocked", "signal-locked"):      # a copy under the locks takes long
        def copy(src, dst, **k):
            if k["locked"]:
                hold_then("locked"); time.sleep(30 if hook == "signal-locked" else 0.3)
            return real_copy(src, dst, **k)
        s.copy_file = copy
    elif hook in ("extra-once", "extra-always", "extra-locks"):
        def copy(src, dst, **k):
            got = real_copy(src, dst, **k)
            if os.sep + "extra-src" + os.sep in src:
                seen["n"] += 1
                if hook == "extra-locks":
                    (T / "extra-locks").write_text(json.dumps([n for n in (*s.LOCKS, "publish", "project-record") if not lock_free(n)]))
                elif hook == "extra-always" or seen["n"] == 1:
                    with open(src, "a", encoding="ascii") as f: f.write("+")
            return got
        s.copy_file = copy
    elif hook == "out-full":                  # the disk of --out fills up
        real = shutil.copy2

        def copy2(a, b):
            seen["n"] += 1
            if seen["n"] == 3: raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC), b)
            return real(a, b)
        s.shutil.copy2 = copy2
    elif hook == "boom":                      # an error nobody foresaw, whose text quotes a content
        def contents(trees):
            raise ValueError("MARKER-quoted-content")
        s.contents = contents
    else:
        raise SystemExit(f"no such hook {hook}")
    sys.exit(s.main(argv))


def free(path):
    """Is the flock on `path` free now? (a file that is not there is)"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


if CHILD:
    kind = sys.argv[2]
    if kind == "writer": child_writer()
    elif kind == "inverse": child_inverse()
    elif kind == "record": child_record()
    elif kind == "hooked": child_hooked(sys.argv[3], sys.argv[4:])
    sys.exit(0)

# ---------------------------------------------------------------------------- the scratch instance
fails = []; ran = []
def check(name, ok, got=None):
    ran.append(name)
    if not ok:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


def git(*args, cwd):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}).stdout.strip()


def config(name="stackshot.toml", edits=()):
    toml = _instance.apply(_instance.base_toml())
    for key, val in (("repo", str(REPO)), ("store", str(STORE)), ("markdown", str(REPO / "board.md")), ("brain", str(T / "brain")),
                     ("state", str(STATE)), ("secrets", str(SECRETS)), ("project_touch", str(T / "touch")), ("rules", str(REPO / "RULES.md"))):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, new in edits:
        toml, n = re.subn(pat, new, toml); assert n == 1, pat
    (T / name).write_text(toml, encoding="utf-8")
    return str(T / name)


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="ascii")


# what a copy holds, by its path in the output, and what it must not hold; every file left out holds a word of its own, looked for in the whole stream
KEPT = {
    "state/for-you.json": '{"g": 0}', "state/ledger.json": "{}", "state/messages.jsonl": '{"a": 1}\n{"a": 2}\n', "state/inbox/q/m1.json": "one", "state/clients/box.json": "client row",
    "state/sub/site/keep.json": "a site folder below the top", "state/sub/backup-x.tar.gz": "a tarball below the top", "state/relay-data/unbound.log": "line\n", "state/search-notes.json": "not the index",
    "state/linked-file.json": "behind a link",
    "store/a/1.json": '{"g": 0}', "store/a/2.json": '{"g": 0}', "store/a/12.json": '{"id": "12"}', "store/anchors.json": "{}", "store/next-id": "12", "store/project-record.json": '{"schema": 1}',
    "store/projects.json": '{"pages": {}}',
    "settings/oauth.env": "MARKER-oauth-env", "settings/keys.json": "MARKER-keys", "settings/relay-data/env": "MARKER-hub-env", "settings/relay-data/google/t.json": "MARKER-google",
    "settings/client-tokens/far-host": "MARKER-issued-token", "settings/clients.json": "{}", "settings/sub/client.url": "below the top",
}
LEFT_OUT = [
    "state/site/versions.json", "state/tmp/atomic", "state/search/index.db", "state/item.lock", "state/inbox/lock", "state/clients/.lock", "state/x.tmp", "state/sub/.y.json.tmp", "state/half.tmp/inner",
    "state/backup-2026-01-01.tar.gz",
    "store/.git/config", "store/a/.git/HEAD", "store/.synced-at", "store/a/.3.json.tmp",
    "settings/client.token", "settings/client.url", "settings/test-launcher", "settings/clean-text-deny", "settings/keys.lock", "settings/oauth.env.tmp",
]
LINKS_LEFT_OUT = ["settings/stackshot.toml", "settings/plugin.json"]      # client files that are links on a real box
SKIPPED = {"state/link-dir": "a link to a directory", "state/nowhere": "a link that leads nowhere", "state/pipe": "not a regular file"}
ROOTS = {"state": STATE, "store": STORE, "settings": SECRETS}


def source_of(rel):
    head, rest = rel.split("/", 1)
    return ROOTS[head] / rest


def build():
    for p in (STATE, STORE, SECRETS, T / "brain/projects", T / "home", REPO):
        p.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(mode=0o700, exist_ok=True)
    for rel, text in KEPT.items():
        if rel != "state/linked-file.json": put(source_of(rel), text)
    for i, rel in enumerate(LEFT_OUT):
        put(source_of(rel), f"NEVERCOPIED{i}END")
    put(T / "outside/real.json", KEPT["state/linked-file.json"]); put(T / "outside/dir/f", "NEVERFOLLOWEDEND")
    os.symlink(T / "outside/real.json", STATE / "linked-file.json")
    os.symlink(T / "outside/dir", STATE / "link-dir")
    os.symlink(T / "outside/no-such", STATE / "nowhere")
    os.mkfifo(STATE / "pipe")
    for i, rel in enumerate(LINKS_LEFT_OUT):
        put(T / f"outside/own{i}", f"NEVERLINKED{i}END"); os.symlink(T / f"outside/own{i}", source_of(rel))
    (STATE / "empty-dir").mkdir()
    os.chmod(SECRETS / "oauth.env", 0o644); os.chmod(STORE / "a/1.json", 0o664)
    git("init", "-q", cwd=REPO)
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "first", cwd=REPO)


build()
os.environ.update(STACKSHOT_CONFIG=config(), STACKSHOT_AUTH="off", HOME=str(T / "home"), XDG_RUNTIME_DIR=str(RUN), XDG_CONFIG_HOME=str(T / "home/.config"),
                  XDG_STATE_HOME=str(T / "home/.state"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CEILING_DIRECTORIES=str(T), COPY_TEST_TMP=str(T))
for k in ("STACKSHOT_URL", "STACKSHOT_READ_ONLY", "BOARD_MCP_CONFIG"):
    os.environ.pop(k, None)

PROCS = []


def start(args, env=None, **kw):
    kw.setdefault("stdout", subprocess.PIPE); kw.setdefault("stderr", subprocess.PIPE)
    p = subprocess.Popen(args, cwd=STACK, env={**os.environ, **(env or {})}, **kw)
    PROCS.append(p)
    return p


def standby(*argv, env=None, hook=None, timeout=120, **kw):
    """(exit code, stdout bytes, stderr text) of one `stackshot standby-copy`, through the command line, or through a hooked child."""
    args = [sys.executable, __file__, "child", "hooked", hook, *argv] if hook else [sys.executable, "-m", "stackshot", "standby-copy", *argv]
    p = start(args, env=env, **kw)
    out, err = p.communicate(timeout=timeout)
    return p.returncode, out or b"", (err or b"").decode("utf-8", "replace")


def child(kind):
    return start([sys.executable, __file__, "child", kind], stdout=None, stderr=None)


def wait_for(cond, what, secs=60.0):
    end = time.time() + secs
    while not cond():
        if time.time() > end:
            raise TimeoutError(what)
        time.sleep(0.01)


def staged():
    return sorted(p.name for p in RUN.iterdir() if p.name.startswith("stackshot-standby-copy-"))


def locks_held():
    from stackshot.tools import standby_copy as s
    held = [n for n in (*s.LOCKS, "publish", "project-record") if not free(STATE / f"{n}.lock")]
    return held + ([] if free(STORE / "next-id") else ["next-id"])


def clean(what):
    check(f"{what}: no staging directory is left", not staged(), staged())
    check(f"{what}: no lock is left held", not locks_held(), locks_held())


def tree_of(root):
    """{path: content, or None for a directory} under root."""
    root = pathlib.Path(root)
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def sources_now():
    """The sources' regular files, the lock files aside (a run makes them)."""
    return {f"{n}/{p.relative_to(r)}": p.read_bytes() for n, r in ROOTS.items() for p in r.rglob("*") if p.is_file() and not p.is_symlink() and not p.name.endswith(".lock")}


def unpack(data, into):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        tar.extractall(into, filter="data")


def manifest_of(d):
    return json.loads((pathlib.Path(d) / "manifest.json").read_text())


def main():
    from stackshot import cli
    from stackshot.core import xlock
    from stackshot.tools import standby_copy as s

    # ------------------------------------------------------------------ 1 the command
    check("the command: `stackshot standby-copy` is listed", cli.PROGRAMS.get("standby-copy", ("",))[0] == "stackshot.tools.standby_copy")
    rc, out, err = standby("-h", env={"STACKSHOT_CONFIG": str(T / "no-such.toml")})
    check("the command: its help names the forms and reads no config", rc == 0 and b"--verify" in out and b"--extra" in out, (rc, out, err))

    # ------------------------------------------------------------------ 2 the stream
    before = sources_now()
    rc, out, err = standby()
    check("stream: a copy of the scratch instance succeeds", rc == 0, err)
    with tarfile.open(fileobj=io.BytesIO(out), mode="r:") as tar:
        members = tar.getmembers()
    files = {m.name for m in members if m.isfile()}
    check("stream: it holds exactly the files that belong, and the manifest", files == set(KEPT) | {"manifest.json"}, (sorted(files - set(KEPT)), sorted(set(KEPT) - files)))
    check("stream: only files and directories", all(m.isfile() or m.isdir() for m in members), [m.name for m in members if not (m.isfile() or m.isdir())])
    check("stream: every mode is private and no user is named", all(m.mode in (0o600, 0o700) and m.uid == 0 and m.gid == 0 and not m.uname and not m.gname for m in members), [(m.name, oct(m.mode), m.uid, m.uname) for m in members])
    check("stream: the manifest is the last member", members[-1].name == "manifest.json", members[-1].name)
    found = [w for w in re.findall(rb"NEVER[A-Z]+\d*END", out)]
    check("stream: no byte of a left-out or unfollowed file is in it", not found, found)
    check("stream: nothing a file holds is printed", "MARKER" not in err and "NEVER" not in err, err)
    unpack(out, T / "got1")
    got = tree_of(T / "got1")
    check("stream: each file arrives as it is", all(got.get(k) == v.encode() for k, v in KEPT.items()), [k for k, v in KEPT.items() if got.get(k) != v.encode()])
    check("stream: an empty directory arrives, and no left-out one", "state/empty-dir" in got and not any(k.split("/")[1:2] in (["site"], ["tmp"], ["search"]) for k in got) and "store/.git" not in got, sorted(got))
    m = manifest_of(T / "got1")
    head = subprocess.run(["git", "-C", STACK, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    check("manifest: format, time, commits and the next id", m["format"] == 1 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", m["time"]) and m["code_commit"] == head
          and m["board_head"] == git("rev-parse", "HEAD", cwd=REPO) and m["next_id"] == 12 and isinstance(m["lock_hold_ms"], int), {k: m.get(k) for k in ("format", "time", "code_commit", "board_head", "next_id", "lock_hold_ms")})
    check("manifest: a sha256 and a size for every file", set(m["files"]) == set(KEPT) and all(v == {"sha256": hashlib.sha256(KEPT[k].encode()).hexdigest(), "size": len(KEPT[k])} for k, v in m["files"].items()), m["files"])
    check("manifest: what was not copied is listed with why", {x["path"]: x["reason"] for x in m["skipped"]} == SKIPPED, m["skipped"])
    check("manifest: and the command says how many", "3 entries not copied" in err and "locks held" in err, err)
    rc, _, err = standby("--verify", str(T / "got1"))
    check("stream: the received tree verifies", rc == 0 and f"verified: {len(KEPT)} files" in err, (rc, err))
    check("stream: the sources are as they were", sources_now() == before)
    clean("stream")
    with open(T / "stream.tar", "wb") as f:
        rc, _, err = standby(stdout=f)
    check("stream: into a file as well", rc == 0 and tarfile.is_tarfile(T / "stream.tar"), err)

    # ------------------------------------------------------------------ 3 --out
    dest = T / "outs/one"; dest.parent.mkdir()
    rc, out, err = standby("--out", str(dest))
    check("out: succeeds and prints nothing on standard output", rc == 0 and out == b"", (rc, out, err))
    modes = {str(p.relative_to(dest)): p.stat().st_mode & 0o777 for p in [dest, *dest.rglob("*")]}
    check("out: every mode is private", all(m in (0o600, 0o700) for m in modes.values()), {k: oct(v) for k, v in modes.items() if v not in (0o600, 0o700)})
    check("out: a file keeps its time", (dest / "store/a/1.json").stat().st_mtime_ns == (STORE / "a/1.json").stat().st_mtime_ns)
    check("out: nothing beside it is left", [p.name for p in dest.parent.iterdir()] == ["one"], list(dest.parent.iterdir()))
    check("out: it verifies", standby("--verify", str(dest))[0] == 0)
    (T / "outs/empty").mkdir()
    check("out: into an empty directory", standby("--out", str(T / "outs/empty"))[0] == 0 and (T / "outs/empty/manifest.json").is_file())
    was = tree_of(dest)
    rc, _, err = standby("--out", str(dest))
    check("out: a directory that holds something is refused and left alone", rc == 1 and "not an empty directory" in err and tree_of(dest) == was, (rc, err))
    rc, _, err = standby("--out", str(STATE / "copy"))
    check("out: inside a source is refused", rc == 1 and "lies inside" in err and not (STATE / "copy").exists(), (rc, err))
    clean("out")

    # ------------------------------------------------------------------ 4 --verify
    def tampered(label, change, word):
        d = T / "tampered"
        shutil.rmtree(d, ignore_errors=True); shutil.copytree(dest, d, symlinks=True)
        change(d)
        rc, out, err = standby("--verify", str(d))
        check(f"verify: {label} exits 1 and says so", rc == 1 and word in err and "MARKER" not in err and not out, (rc, err))

    def rewrite_manifest(d, fn):
        m = manifest_of(d); fn(m); (d / "manifest.json").write_text(json.dumps(m))
    tampered("a byte changed, the size kept", lambda d: (d / "settings/oauth.env").write_text("MARKER-oauth-enV"), "changed: settings/oauth.env")
    tampered("a file cut short", lambda d: (d / "state/messages.jsonl").write_text('{"a": 1}\n'), "changed: state/messages.jsonl")
    tampered("a file missing", lambda d: (d / "store/a/2.json").unlink(), "missing: store/a/2.json")
    tampered("a file too many", lambda d: (d / "store/a/99.json").write_text("{}"), "extra: store/a/99.json")
    tampered("a file at the top too many", lambda d: (d / "note").write_text("x"), "extra: note")
    tampered("a directory too many", lambda d: (d / "state/more").mkdir(), "extra directory: state/more")
    tampered("a directory missing", lambda d: (d / "state/empty-dir").rmdir(), "missing directory: state/empty-dir")

    def linked(d):
        (d / "store/next-id").unlink(); os.symlink(STORE / "next-id", d / "store/next-id")
    tampered("a link in a file's place", linked, "neither a file nor a directory: store/next-id")
    tampered("no manifest", lambda d: (d / "manifest.json").unlink(), "cannot be read")
    tampered("a manifest cut short", lambda d: (d / "manifest.json").write_bytes((d / "manifest.json").read_bytes()[:200]), "not a whole manifest")
    tampered("another format", lambda d: rewrite_manifest(d, lambda m: m.update(format=2)), "not a manifest of format")
    tampered("a path that climbs out", lambda d: rewrite_manifest(d, lambda m: m["files"].update({"../outside/real.json": {"sha256": "0", "size": 0}})), "malformed")
    tampered("an absolute directory", lambda d: rewrite_manifest(d, lambda m: m["dirs"].append("/etc")), "malformed")
    rc, _, err = standby("--verify", str(dest), env={"STACKSHOT_CONFIG": str(T / "no-such.toml")})
    check("verify: needs no config of the server", rc == 0, (rc, err))
    cut = T / "cut"
    try:
        unpack((T / "stream.tar").read_bytes()[:6000], cut)
    except (tarfile.TarError, OSError):
        pass
    cut.mkdir(exist_ok=True)
    check("verify: a stream cut short never verifies", standby("--verify", str(cut))[0] == 1)
    check("verify: not a directory fails", standby("--verify", str(T / "no-such"))[0] == 1)
    check("verify: takes no --out", standby("--verify", str(dest), "--out", str(T / "x"))[0] == 2)

    # ------------------------------------------------------------------ 5 refusals
    def refused(label, word, env=None, **kw):
        rc, out, err = standby(env=env, **kw)
        check(f"refusal: {label}: exit 3, a clear line, nothing written", rc == 3 and "refused" in err and word in err and not out, (rc, err, out[:80]))
        check(f"refusal: {label}: no staging directory", not staged(), staged())
    refused("deploy_ssh names another box", "not the server host", env={"STACKSHOT_CONFIG": config("other.toml", [(r'(?m)^deploy_ssh = ""', 'deploy_ssh = "far-host"')])})
    refused("[server] box = false", "not the server host", env={"STACKSHOT_CONFIG": config("nobox.toml", [(r'(?m)^# box = true', 'box = false')])})
    refused("a read-only standby", "read-only standby", env={"STACKSHOT_READ_ONLY": "1"})
    refused("the cross-process locks off", "cross_process", env={"STACKSHOT_CONFIG": config("nolocks.toml", [(r'(?m)^cross_process = true', 'cross_process = false')])})
    master, slave = pty.openpty()
    try:
        p = start([sys.executable, "-m", "stackshot", "standby-copy"], stdout=slave)
        err = p.communicate(timeout=60)[1].decode()
        check("refusal: a terminal for the stream", p.returncode == 3 and "terminal" in err and not staged(), (p.returncode, err))
    finally:
        os.close(master); os.close(slave)
    rc, out, err = standby(env={"XDG_RUNTIME_DIR": str(T / "no-run")})
    check("failure: no runtime directory", rc == 1 and "runtime directory" in err and not out, (rc, err))
    rc, out, err = standby(env={"XDG_RUNTIME_DIR": str(STATE / "empty-dir")})
    check("failure: a runtime directory inside a source", rc == 1 and "lies inside" in err and not out, (rc, err))
    os.rename(SECRETS, T / "secrets.away")
    try:
        rc, out, err = standby()
        check("failure: a folder that is not there", rc == 1 and "settings folder" in err and not out, (rc, err))
    finally:
        os.rename(T / "secrets.away", SECRETS)
    rc, out, err = standby(env={"STACKSHOT_CONFIG": config("nohead.toml", [(r'(?m)^repo = "[^"]*"', f'repo = "{T / "outside"}"')])})
    check("failure: the board's head cannot be read", rc == 1 and "head commit" in err and not out, (rc, err))
    clean("refusals")

    # ------------------------------------------------------------------ 6 the locks
    made = {}
    for path in sorted(pathlib.Path(STACK, "stackshot").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "XLock" and n.args:
                a = n.args[0]
                name = a.value if isinstance(a, ast.Constant) else consts.get(getattr(a, "id", ""))
                if path.name == "standby_copy.py":
                    continue
                made.setdefault(name or f"unread at {path.name}:{n.lineno}", path.name)
    check("locks: every XLock the package makes is one the command takes, or one it says it does not", set(made) == set(s.LOCKS) | set(s.LOCKS_NOT_TAKEN), (sorted(set(made) ^ (set(s.LOCKS) | set(s.LOCKS_NOT_TAKEN))), made))
    ranks = [xlock.ORDER[n] for n in s.LOCKS if n in xlock.ORDER]
    check("locks: in the order of core/xlock.py, the two outside it last", ranks == sorted(ranks) and set(xlock.ORDER) <= set(s.LOCKS) and s.LOCKS[-2:] == ("anchors", "machine-anchors"), s.LOCKS)
    from stackshot.core import store as core_store
    from stackshot.web import publish
    check("locks: the publish lock and the id counter are the files their writers lock", publish.LOCK == STATE / "publish.lock" and core_store.NEXT_ID == STORE / "next-id", (publish.LOCK, core_store.NEXT_ID))
    for name, path in [(n, STATE / f"{n}.lock") for n in s.LOCKS] + [("publish", publish.LOCK), ("next-id", core_store.NEXT_ID)]:
        fd = os.open(path, os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            rc, out, err = standby("--lock-timeout", "0.4")
            others = [n for n in locks_held() if n != name]
        finally:
            os.close(fd)
        check(f"locks: {name} held elsewhere fails the run in its time, naming it", rc == 1 and f"the {name} lock was not free" in err and not out, (rc, err))
        check(f"locks: {name}: no other lock is kept and no staging directory", not others and not staged(), (others, staged()))
    holder = child("record")
    wait_for((T / "held-record").exists, "the record holder")
    rc, out, err = standby("--lock-timeout", "0.4")
    check("locks: the project record's writer holds the command off", rc == 1 and "the project-record lock was not free" in err and not out, (rc, err))
    holder.kill(); holder.wait()
    fd = os.open(STATE / "item.lock", os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = start([sys.executable, "-m", "stackshot", "standby-copy", "--lock-timeout", "60"], stdout=subprocess.DEVNULL)
        wait_for(lambda: not free(publish.LOCK), "the command to take the publish lock")
        wait_for(lambda: free(publish.LOCK), "the command to let go while it cannot have the item lock", 20)
        check("locks: while one lock is not free the others are let go again", p.poll() is None)
    finally:
        os.close(fd)
    err = p.communicate(timeout=60)[1].decode()
    check("locks: a hold that ends is waited out", p.returncode == 0, err)
    holder = child("inverse")
    wait_for((T / "held-inverse").exists, "the inverse holder")
    rc, _, err = standby("--lock-timeout", "30")
    check("locks: a holder that takes two the other way round is let through, and the command follows", rc == 0 and holder.wait(timeout=30) == 0 and (T / "inverse-done").exists(), (rc, err))
    clean("locks")

    # ------------------------------------------------------------------ 7 concurrency
    writer = child("writer")
    wait_for(lambda: (T / "writer-g").exists() and int((T / "writer-g").read_text() or 0) > 5, "the writer")
    torn = 0
    for _ in range(400):
        a = json.loads((STORE / "a/1.json").read_text())["g"]
        time.sleep(0.003)
        torn += a != json.loads((STORE / "a/2.json").read_text())["g"]
        if torn: break
    check("concurrency: the control: reading the same two files with no lock sees two moments", torn > 0, torn)
    seen = []
    for i in range(8):
        d = T / f"run{i}"
        rc, _, err = standby("--out", str(d), hook="smalllog" if i % 2 else None)      # every other one adds to its first copy of the log
        if rc != 0:
            check(f"concurrency: copy {i} succeeds under the writer", False, err); continue
        g1, g2 = (json.loads((d / f"store/a/{n}.json").read_text())["g"] for n in (1, 2))
        fy = json.loads((d / "state/for-you.json").read_text())["g"]
        raw = (d / "state/writer.jsonl").read_bytes()
        lines = [json.loads(x)["g"] for x in raw.splitlines()]
        counter = int((d / "store/next-id").read_text())
        highest = max(int(p.stem) for p in (d / "store/a").glob("*.json"))
        check(f"concurrency: copy {i} is one moment (both items, the For you list, the log's last line)", g1 == g2 == fy == lines[-1], (g1, g2, fy, lines[-1:]))
        check(f"concurrency: copy {i}: the log is whole lines, none missing", raw.endswith(b"\n") and lines == list(range(1, len(lines) + 1)), (len(lines), raw[-80:]))
        check(f"concurrency: copy {i}: the id counter is behind no item in it", counter >= highest and manifest_of(d)["next_id"] == counter, (counter, highest))
        check(f"concurrency: copy {i} verifies", s.verify(str(d))[1] == [], s.verify(str(d))[1])
        seen.append(g1)
    (T / "writer-stop").write_text("1")
    check("concurrency: the writer ran on all the while and ended well", writer.wait(timeout=30) == 0 and len(set(seen)) == len(seen) == 8 and seen == sorted(seen), seen)
    clean("concurrency")

    # ------------------------------------------------------------------ 8 between the first copy and the locks
    put(STATE / "big.jsonl", "".join(f'{{"n": {i}}}\n' for i in range(500))); put(STATE / "rewritten.log", "o" * 300 + "\n"); put(STATE / "rotated.log", "old\n" * 50)
    put(STATE / "same.json", "AAAA"); put(STATE / "gone.json", "gone"); put(STATE / "was-dir/in.json", "inside"); put(STATE / "was-file", "a file")
    time.sleep(2.2)      # long enough ago that the first copy of an unchanged file would be trusted
    d = T / "between"
    rc, _, err = standby("--out", str(d), hook="between")
    check("between: succeeds", rc == 0, err)
    if rc == 0:
        now = {k[len("state/"):]: v for k, v in sources_now().items() if k.startswith("state/")}
        now["big.jsonl"] = now["big.jsonl"][:now["big.jsonl"].rfind(b"\n") + 1]
        for rel in ("big.jsonl", "rewritten.log", "rotated.log", "same.json", "added.json", "was-dir", "was-file/in.json"):
            got = (d / "state" / rel).read_bytes() if (d / "state" / rel).is_file() else None
            check(f"between: {rel} is as it stood under the locks", got == now.get(rel) and got is not None, (got and got[-60:], now.get(rel, b"")[-60:]))
        check("between: the removed file and folder entry are not in it", not (d / "state/gone.json").exists() and not (d / "state/was-dir/in.json").exists())
        check("between: the id counter is read again", (d / "store/next-id").read_text() == "77" and manifest_of(d)["next_id"] == 77)
        check("between: it verifies", s.verify(str(d))[1] == [], s.verify(str(d))[1])
    (STORE / "next-id").write_text("12")
    clean("between")

    # ------------------------------------------------------------------ 9 failure
    put(STATE / "bulk.json", "b" * 3_000_000)
    rc, out, err = standby(preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000)))
    check("failure: a write error in the staging directory", rc == 1 and os.strerror(errno.EFBIG) in err and not out, (rc, err, out[:80]))
    clean("failure: staging write")
    with open("/dev/full", "wb") as full:
        rc, _, err = standby(stdout=full)
    check("failure: the stream's device is full", rc == 1 and os.strerror(errno.ENOSPC) in err, (rc, err))
    clean("failure: full device")
    p = start([sys.executable, "-m", "stackshot", "standby-copy"])
    p.stdout.read(100); p.stdout.close()
    err = p.stderr.read().decode(); p.wait(timeout=60)
    check("failure: the reader of the stream leaves", p.returncode == 1 and os.strerror(errno.EPIPE) in err and "Exception ignored" not in err, (p.returncode, err))
    clean("failure: broken pipe")
    (T / "outfull").mkdir()
    rc, _, err = standby("--out", str(T / "outfull/copy"), hook="out-full")
    check("failure: the disk of --out fills: no directory, nothing beside it", rc == 1 and os.strerror(errno.ENOSPC) in err and not list((T / "outfull").iterdir()), (rc, err, list((T / "outfull").iterdir())))
    clean("failure: --out write")
    rc, out, err = standby(hook="unsettled")
    check("failure: a folder that never settles, named", rc == 1 and "kept changing" in err and "state/busy.json" in err and not out, (rc, err))
    clean("failure: unsettled")
    (STATE / "busy.json").unlink()
    put(STATE / "vanishing.json", "here")
    d = T / "vanish"
    rc, _, err = standby("--out", str(d), hook="vanish")
    check("failure: a file that goes mid-copy is simply not in a settled picture", rc == 0 and not (d / "state/vanishing.json").exists() and s.verify(str(d))[1] == [], (rc, err))
    rc, out, err = standby("--max-hold", "0.1", hook="slowlocked")
    check("failure: the copy under the locks takes longer than it may", rc == 1 and "did not finish within" in err and not out, (rc, err))
    clean("failure: longest hold")
    rc, out, err = standby(hook="boom")
    check("failure: an unforeseen error names its kind and place, never its text", rc == 1 and "ValueError at" in err and "MARKER" not in err and not out, (rc, err))
    clean("failure: unforeseen")

    for signame in s.SIGNALS:
        num = getattr(signal, signame)
        fd = os.open(STATE / "item.lock", os.O_RDONLY)      # while a lock is waited for
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            p = start([sys.executable, "-m", "stackshot", "standby-copy"])
            wait_for(lambda: staged() and not free(publish.LOCK), "the command to wait for the item lock")
            p.send_signal(num)
            out, err = p.communicate(timeout=60)
        finally:
            os.close(fd)
        check(f"signal {signame} while a lock is waited for: 128 + n, nothing written", p.returncode == 128 + num and not out and b"stopped by signal" in err, (p.returncode, err))
        clean(f"signal {signame} while waiting")
        (T / "held-locked").unlink(missing_ok=True)          # while the locks are held
        p = start([sys.executable, __file__, "child", "hooked", "signal-locked"])
        wait_for((T / "held-locked").exists, "the copy under the locks")
        check(f"signal {signame}: (the locks are held at that point)", "item" in locks_held(), locks_held())
        p.send_signal(num)
        out, err = p.communicate(timeout=60)
        check(f"signal {signame} while the locks are held: 128 + n, nothing written", p.returncode == 128 + num and not out, (p.returncode, err))
        clean(f"signal {signame} with the locks held")
        p = start([sys.executable, "-m", "stackshot", "standby-copy"])      # while the output is blocked: 3 MB into a pipe nobody reads
        first = p.stdout.read(512)
        time.sleep(0.2)
        check(f"output: the locks are let go before the output ({signame})", len(first) == 512 and p.poll() is None and not locks_held(), (p.poll(), locks_held()))
        names = staged()
        check(f"output: the staging directory is private and locked ({signame})", len(names) == 1 and (RUN / names[0]).stat().st_mode & 0o777 == 0o700 and not free(RUN / names[0]), names)
        p.send_signal(num)
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill(); p.wait()
        check(f"signal {signame} while the output is blocked: ends with 128 + n", p.returncode == 128 + num, (p.returncode, p.stderr.read()))
        p.stdout.close(); p.stderr.close()
        clean(f"signal {signame} during the output")
    (STATE / "bulk.json").unlink()

    old, held_old, young, other = (RUN / n for n in ("stackshot-standby-copy-old", "stackshot-standby-copy-held", "stackshot-standby-copy-young", "someone-else"))
    for p_ in (old, held_old, young, other):
        (p_ / "state").mkdir(parents=True)
    past = time.time() - 3600
    for p_ in (old, held_old, other):
        os.utime(p_, (past, past))
    fd = os.open(held_old, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        rc, _, err = standby()
        check("leftovers: an old staging directory nobody holds is removed; a held one, a young one and another's stay", rc == 0 and not old.exists() and held_old.exists() and young.exists() and other.exists(), (rc, err, staged()))
    finally:
        os.close(fd)
        for p_ in (held_old, young, other):
            shutil.rmtree(p_, ignore_errors=True)

    # ------------------------------------------------------------------ 10 extra directories
    x1, x2 = T / "extra-src", T / "extra-two"
    put(x1 / "col/key.json", "k1"); put(x1 / "col/index.lock", "an extra directory is copied whole"); put(x2 / "t.tmp", "t2")
    d = T / "x1"
    rc, _, err = standby("--out", str(d), "--extra", str(x1))
    m = manifest_of(d) if rc == 0 else {}
    check("extra: --extra copies the directory whole, and the manifest names its source", rc == 0 and tree_of(d / "extra/0") == tree_of(x1) and m["extra"] == [{"dir": "extra/0", "source": str(x1)}] and s.verify(str(d))[1] == [], (rc, err))
    with_config = {"STACKSHOT_CONFIG": config("extra.toml", [(r'(?m)^extra_dirs = \[\]', f'extra_dirs = ["{x2}"]')])}
    d = T / "x2"
    rc, _, err = standby("--out", str(d), "--extra", str(x1), "--extra", str(x2), env=with_config)
    m = manifest_of(d) if rc == 0 else {}
    check("extra: [standby_copy] extra_dirs and --extra add up, one copy of a directory named twice", rc == 0 and [e["source"] for e in m["extra"]] == [str(x2), str(x1)] and tree_of(d / "extra/0") == tree_of(x2), (rc, err, m.get("extra")))
    rc, out, err = standby()
    check("extra: without them there is no extra folder", rc == 0 and b"extra/0" not in out, err)
    d = T / "x3"
    rc, _, err = standby("--out", str(d), "--extra", str(x1), hook="extra-locks")
    check("extra: copied with every lock free", rc == 0 and json.loads((T / "extra-locks").read_text()) == [], (rc, err))
    d = T / "x4"
    rc, _, err = standby("--out", str(d), "--extra", str(x1), hook="extra-once")
    check("extra: one written during its copy is copied again, as it then stands", rc == 0 and tree_of(d / "extra/0") == tree_of(x1), (rc, err))
    rc, out, err = standby("--extra", str(x1), hook="extra-always")
    check("extra: one that never settles fails the run", rc == 1 and "did not settle" in err and not out, (rc, err))
    clean("extra: unsettled")
    rc, out, err = standby("--extra", str(T / "no-such"))
    check("extra: one that is not there fails the run", rc == 1 and "is not there" in err and not out, (rc, err))
    for label, p_ in (("a parent of the settings folder", T), ("a folder inside the state dir", STATE / "empty-dir"), ("the settings folder", SECRETS)):
        rc, out, err = standby("--extra", str(p_))
        check(f"extra: {label} is refused, so no left-out file comes in by that door", rc == 1 and "overlaps" in err and not out, (rc, err))
    clean("extra")


try:
    main()
except BaseException as e:      # noqa: BLE001  — said as a failed check, so the processes below are still ended
    import traceback
    traceback.print_exc()
    check("the scenario ran to its end", False, repr(e))
finally:
    (T / "writer-stop").write_text("1")
    for p in PROCS:             # only the processes this suite started, each by its own handle
        if p.poll() is None:
            p.kill()
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass

print(("ok" if not fails else "FAILED") + f": standby copy scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
