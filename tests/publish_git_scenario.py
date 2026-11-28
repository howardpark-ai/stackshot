"""Scenario test for the publisher's git step (`publish._gitsync`): it never rebases, stashes or checks out in the live store clone. Fixture data only:
a bare repository acting as the mirror (origin) and clones acting as the store and another writer, all in scratch folders from tests/_scratch.py;
no network, nothing of the host's touched.

Covers: the store ahead only (pushed, no rebase in the reflog, no note); the store behind only (fast-forwarded, the newer remote file in the working
tree, an uncommitted edit kept, and a refusal where the edit is on a file the mirror changed, naming the file); a store DIVERGED on disjoint files (healed
by a merge made off the live tree: both writers' files present, pushed, the uncommitted item file untouched, the merge's author the store's configured
identity, else the committer in the environment, else its last commit's committer, never an author; a refusal of the fast-forward onto an uncommitted edit
reported); a store diverged on the same files (a real
conflict: nothing in the working tree changes, no stash, HEAD and the refs unchanged, nothing pushed, one line on stderr with the asymmetric counts, repeated
at most hourly per process; `publish.py flush` against it exits non-zero); a poller that reads a tracked, uncommitted item file every 20 ms while a
conflicting publish runs over a few hundred files and finds it never differs from the uncommitted content; a refused push, a non-fast-forward rejection
and a reason line that carries an address, each reported once an hour; a failed fetch, a quiet publish, a file staged by a session, a ref git cannot
compare; a brain's pages (publish_pages(): off by default and then raising, one commit per put of exactly the files named with the person as author and
the board's bot as committer, none when unchanged, a removal and the last page's removal committed, every path, author and folder state that could reach
outside pages/, name more than one file or remove what nobody named refused before anything is staged, a file and a folder that swapped places going out
only with both sides named, a .git part, a nested repository, a folder that cannot be read, an unmerged page never read as unchanged or removed, an
assume-unchanged one committed as on disk, a held index.lock refused up front, a failed commit (a refusing hook, git's words not UTF-8, git that cannot
start) raising with the store clone's index byte for byte as it was and never taken up later by another author or the board's own publish, that index
locked right after the commit said with how to clear it, what a session staged in that index never dropped, unstaged or committed (a new file in a folder
that became a file, a file where a page needs a folder, files outside pages/, a staged removal and edit under a failed put), a submodule never removed
unnamed whatever .gitmodules or diff.ignoreSubmodules hide, no automatic gc from the page commit (a month-old blob only a staged entry holds kept), a real
SIGINT to a child publisher while git commits (git ends, no lock of git's or temporary file left, the interrupt said), [paths] repo below the top refused,
a mirror out of reach said, more paths than one call takes, a branch with no upstream, the board's merge after a page its own, the publish lock across
processes, threads and a nested hold, two boards' repositories apart, the board's own publish exactly as before);
and the same conflicting run through the old `rebase --autostash` step (kept below as
`old_gitsync`), which the poller catches, so the check can fail.

The suite gives git a global config of its own (user.useConfigOnly, no identity): no commit of it may lean on the host's own git identity.

    tests/run-suite publish_git        -> exit 0 / 1"""
import contextlib, fcntl, io, os, pathlib, re, shlex, shutil, signal, subprocess, sys, tempfile, threading, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pubgit-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
for d in ("state", "secrets"): (T / d).mkdir(parents=True)
(T / "gitconfig").write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")       # the host's ~/.gitconfig never takes part: no identity to fall back on
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(T / "gitconfig"))
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

def git(cwd, *a, ok=True) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)
    assert r.returncode == 0 or not ok, (a, r.stderr)
    return r.stdout.strip()

from stackshot.web import publish as P

BULK = 300                        # files both sides change: every one conflicts in a replay
ITEM = "board-data/item-1.json"
DIRTY = '{"id": 1, "state": "uncommitted edit"}\n'
def write(repo, name, text): p = repo / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
SEED = ("-c", "user.name=Seed", "-c", "user.email=seed@x")      # a fixture commit's own identity, for where the environment has none (inside as_bot()); the environment's wins where it has one
def commit(repo, msg, **files):
    for name, text in files.items(): write(repo, name, text)
    git(repo, "add", "-A"); git(repo, *SEED, "commit", "-q", "-m", msg); return git(repo, "rev-parse", "HEAD")
_n = [0]
def world(bulk=BULK):
    """A fresh bare origin, the store (a clone that tracks it) and another writer's clone. Returns (origin, store, other)."""
    _n[0] += 1; k = _n[0]
    origin = T / f"origin{k}.git"; git(T, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = T / f"seed{k}"; git(T, "clone", "-q", str(origin), str(seed))
    commit(seed, "first", **{"board.md": "board\n", ITEM: '{"id": 1, "state": "committed"}\n', **{f"bulk/f-{i:03d}.txt": "base\n" for i in range(bulk)}})
    git(seed, "branch", "-M", "main"); git(seed, "push", "-q", "-u", "origin", "main")
    store = T / f"store{k}"; git(T, "clone", "-q", str(origin), str(store))
    other = T / f"other{k}"; git(T, "clone", "-q", str(origin), str(other))
    return origin, store, other
def run(gitsync, *a):
    err = io.StringIO()
    with contextlib.redirect_stderr(err): gitsync(*a)
    return err.getvalue()
def use(store): P.REPO = store; P._NOTED.clear()
def state(repo): return (git(repo, "rev-parse", "HEAD"), git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"), git(repo, "status", "--porcelain"), git(repo, "stash", "list"))
def rebased(repo): return "rebase" in git(repo, "reflog", "show", "--all", "-n", "200", ok=False).lower()

def porcelain(repo): return git(repo, "status", "--porcelain")
@contextlib.contextmanager
def wrapped_git(after=None, calls=None, on="fetch", when=None):
    """Patch publish._git: record every call's arguments, and run `after()` once the call named `on` (the fetch, by default) has returned: another writer pushing, or a session committing, in between."""
    real = P._git
    def w(*a, **k):
        r = real(*a, **k)
        if calls is not None: calls.append(a)
        if after is not None and (when(a) if when else a[:1] == (on,)): after()
        return r
    P._git = w
    try: yield
    finally: P._git = real
@contextlib.contextmanager
def no_ident():
    """No identity in the environment or the global config: only what the store clone carries itself."""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    glob = os.environ.get("GIT_CONFIG_GLOBAL"); os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    try: yield
    finally: os.environ["GIT_CONFIG_GLOBAL"] = glob; os.environ.update(saved)
def commit_as(repo, who, msg, by=None, **files):
    """A commit by `who` as author, and as committer too unless `by` names another."""
    with no_ident():
        for k, name in (("AUTHOR", who), ("COMMITTER", by or who)): os.environ[f"GIT_{k}_NAME"] = name; os.environ[f"GIT_{k}_EMAIL"] = f"{name.lower().replace(' ', '.')}@x"
        try: return commit(repo, msg, **files)
        finally:
            for k in ("AUTHOR", "COMMITTER"): os.environ.pop(f"GIT_{k}_NAME", None); os.environ.pop(f"GIT_{k}_EMAIL", None)

def old_gitsync(msg: str, *paths: str) -> None:
    """The step as it was: fetch, `rebase --autostash` onto origin/main (aborted on a conflict), push. Kept only to show the poller catches it."""
    have = [p for p in paths if (P.REPO / p).exists()]
    for p in have: P._git("add", "-A", "--", p)
    committed = False
    if have and P._git("diff", "--cached", "--quiet", "--", *have).returncode != 0:
        P._git("commit", "--quiet", "--only", "-m", msg, "--", *have); committed = True
    if not committed and P._git("rev-list", "--count", "@{u}..HEAD").stdout.strip() in ("", "0"): return
    if P._git("fetch", "--quiet", "origin", "main").returncode != 0: return
    if P._git("rebase", "--autostash", "--quiet", "origin/main").returncode != 0:
        P._git("rebase", "--abort"); return
    P._git("push", "--quiet", "origin", "main")

# ============================================================= 1. the store ahead only: pushed, no rebase, nothing said
origin, store, other = world(bulk=3); use(store)
write(store, "board.md", "board, newer\n"); write(store, ITEM, '{"id": 1, "state": "newer"}\n')
err = run(P._gitsync, "board: newer", "board.md", "board-data")
check("ahead: the commit reached the mirror", git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and git(store, "log", "-1", "--format=%s") == "board: newer", (git(origin, "rev-parse", "main"), git(store, "rev-parse", "HEAD")))
check("ahead: no rebase in the reflog, no stash, nothing said", not rebased(store) and git(store, "stash", "list") == "" and err == "", (err, git(store, "reflog", "-n", "5")))
err = run(P._gitsync, "board: again", "board.md", "board-data")
check("ahead: a quiet publish after it changes nothing and says nothing", err == "" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), err)

# ============================================================= 2. the store behind only: fast-forwarded, the working tree gets the new file
origin, store, other = world(bulk=3); use(store)
# a commit of the store's that reached the mirror by another way (its tracking ref is stale), then another writer's commit on top of it
write(store, "board.md", "board, store's\n"); git(store, "add", "-A"); git(store, "commit", "-q", "-m", "store's"); S1 = git(store, "rev-parse", "HEAD")
git(store, "push", "-q", "origin", "HEAD:main"); git(store, "update-ref", "refs/remotes/origin/main", "HEAD~1")
git(other, "pull", "-q", "--ff-only", "origin", "main"); O1 = commit(other, "newer elsewhere", **{"item-2.json": '{"id": 2}\n'}); git(other, "push", "-q", "origin", "main")
write(store, ITEM, DIRTY)                                         # an uncommitted edit stays
err = run(P._gitsync, "board: none", "board.md")
check("behind: fast-forwarded to the mirror's commit", git(store, "rev-parse", "HEAD") == O1, (git(store, "rev-parse", "HEAD"), O1))
check("behind: the newer remote file is in the working tree, the uncommitted edit kept, nothing said, no rebase",
      (store / "item-2.json").read_text() == '{"id": 2}\n' and (store / ITEM).read_text() == DIRTY and err == "" and not rebased(store), err)

# the same, with an uncommitted edit on a file the mirror changed: git refuses, the note names the file, nothing moves
def behind_world(keep_notes=False, overlap=True):
    """The store's own commit is on the mirror already (its tracking ref is stale, so a publish goes on to fetch); another writer then changed the item file."""
    origin, store, other = world(bulk=3); P.REPO = store
    if not keep_notes: P._NOTED.clear()
    write(store, "board.md", "board, store's\n"); git(store, "add", "-A"); git(store, "commit", "-q", "-m", "store's"); git(store, "push", "-q", "origin", "HEAD:main"); git(store, "update-ref", "refs/remotes/origin/main", "HEAD~1")
    git(other, "pull", "-q", "--ff-only", "origin", "main"); O1 = commit(other, "item changed elsewhere", **({ITEM: '{"id": 1, "state": "elsewhere"}\n'} if overlap else {"pages/p.md": "p\n"})); git(other, "push", "-q", "origin", "main")
    write(store, ITEM, DIRTY); return origin, store, other, O1
origin, store, other, O1 = behind_world(); before = state(store)
err = run(P._gitsync, "board: none", "board.md")
check("behind, dirty overlap: the refusal is reported once, naming the file, and nothing moved", len(err.splitlines()) == 1 and err.startswith("publish: fast-forward to the mirror failed: ") and ITEM in err and state(store) == before and (store / ITEM).read_text() == DIRTY, err)
err = run(P._gitsync, "board: none", "board.md")
check("behind, dirty overlap: said once an hour", err == "", err)

# ============================================================= 3. diverged on the same files: a real conflict, the live tree is never touched
def diverged(gitsync, bulk=BULK):
    origin, store, other = world(bulk); use(store)
    commit(other, "mirror side", **{f"bulk/f-{i:03d}.txt": "origin side\n" for i in range(bulk)}); git(other, "push", "-q", "origin", "main")
    commit(store, "store side", **{f"bulk/f-{i:03d}.txt": "store side\n" for i in range(bulk)})
    write(store, ITEM, DIRTY)                                     # tracked, not committed: what a write in flight looks like
    before = state(store); mirror = git(origin, "rev-parse", "main")
    seen = set(); stop = threading.Event(); samples = [0]
    def poll():
        while not stop.is_set():
            try: seen.add((store / ITEM).read_text())
            except OSError: seen.add(None)
            samples[0] += 1; time.sleep(0.02)
    th = threading.Thread(target=poll, daemon=True); th.start()
    try: err = run(gitsync, "board: x", "board.md")
    finally: stop.set(); th.join()
    return dict(err=err, before=before, after=state(store), seen=seen, samples=samples[0], pushed=git(origin, "rev-parse", "main") != mirror, store=store, origin=origin, other=other, rebased=rebased(store))
r = diverged(P._gitsync)
check("diverged: HEAD, its branch, the status and the stash list are as they were", r["before"] == r["after"] and r["before"][3] == "", (r["before"], r["after"]))
check("diverged: the uncommitted item file is read as itself at every sample (never the committed or a replayed version)", r["seen"] == {DIRTY} and r["samples"] >= 1, (r["seen"], r["samples"]))
check("diverged: nothing pushed, no rebase, no rebase folder left", not r["pushed"] and not r["rebased"] and not (r["store"] / ".git/rebase-merge").exists() and not (r["store"] / ".git/rebase-apply").exists())
lines = r["err"].splitlines()
check("diverged: one line on stderr, saying the counts", len(lines) == 1 and lines[0] == "publish: the store and its mirror have diverged and conflict; the live store is left as it is, and it needs a manual merge (local 1 ahead, origin 1 ahead)", r["err"])
err2 = run(P._gitsync, "board: x", "board.md")
check("diverged: a second publish within the hour says nothing and still changes nothing", err2 == "" and state(r["store"]) == r["after"], err2)
P._NOTED["diverged"] -= P._NOTE_EVERY + 1
err3 = run(P._gitsync, "board: x", "board.md")
check("diverged: after the hour the line comes once more", len(err3.splitlines()) == 1 and "have diverged" in err3, err3)

# asymmetric counts: the store 2 ahead, the mirror 1 ahead, so a swapped pair is seen
origin, store, other = world(bulk=3); use(store)
commit(other, "mirror side", **{"board.md": "mirror\n"}); git(other, "push", "-q", "origin", "main")
commit(store, "store side 1", **{"board.md": "store 1\n"}); commit(store, "store side 2", **{"board.md": "store 2\n"})
before = state(store); mirror = git(origin, "rev-parse", "main")
err = run(P._gitsync, "board: x", "board.md")
check("diverged: asymmetric counts read local 2, origin 1", err.strip().endswith("(local 2 ahead, origin 1 ahead)") and state(store) == before and git(origin, "rev-parse", "main") == mirror, err)

# `merge-tree` itself failing (git older than 2.38 has no `--write-tree`) is said as such, never as a conflict, and nothing moves
origin, store, other = world(bulk=3); use(store)
commit(other, "mirror side", **{"pages/p.md": "p\n"}); git(other, "push", "-q", "origin", "main"); commit(store, "store side", **{"board-data/a.json": "{}\n"})
before = state(store); mirror = git(origin, "rev-parse", "main"); real_git = P._git
P._git = lambda *a, **k: subprocess.CompletedProcess(a, 129, "", "usage: git merge-tree") if a[:1] == ("merge-tree",) else real_git(*a, **k)
try: err = run(P._gitsync, "board: x", "board.md")
finally: P._git = real_git
check("diverged, merge-tree fails: one line naming git's exit status, not a conflict; nothing moved or pushed", len(err.splitlines()) == 1 and "could not check" in err and "exit 129" in err and "conflict" not in err and state(store) == before and git(origin, "rev-parse", "main") == mirror, err)

# `merge-base` failing although both heads read (an object git cannot load) is said as such, never as a divergence, and nothing moves
origin, store, other = world(bulk=3); use(store)
commit(other, "mirror side", **{"pages/p.md": "p\n"}); git(other, "push", "-q", "origin", "main"); commit(store, "store side", **{"board-data/a.json": "{}\n"})
before = state(store); mirror = git(origin, "rev-parse", "main"); real_git = P._git
P._git = lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "fatal: bad object") if a[:1] == ("merge-base",) else real_git(*a, **k)
try: err = run(P._gitsync, "board: x", "board.md")
finally: P._git = real_git
check("merge-base fails: one line naming git's exit status, not a divergence; nothing moved or pushed", len(err.splitlines()) == 1 and "could not compare" in err and "exit 128" in err and "diverged" not in err and state(store) == before and git(origin, "rev-parse", "main") == mirror, err)

# ============================================================= 3b. diverged on DISJOINT files: healed by a merge made off the live tree
def disjoint(item_upstream=False, store_cfg=None, last_author=None, ident=False, autostash=False, last_committer=None, env_ident=None):
    origin, store, other = world(bulk=3); use(store)
    up = {"pages/p.md": "page, written elsewhere\n"}
    if item_upstream: up[ITEM] = '{"id": 1, "state": "elsewhere"}\n'
    O1 = commit(other, "pages from elsewhere", **up); git(other, "push", "-q", "origin", "main")
    if last_author: S1 = commit_as(store, last_author, "store data", by=last_committer, **{"board-data/a.json": '{"a": 1}\n'})
    else: S1 = commit(store, "store data", **{"board-data/a.json": '{"a": 1}\n'})
    if store_cfg: git(store, "config", "user.name", store_cfg[0]); git(store, "config", "user.email", store_cfg[1])
    if autostash: git(store, "config", "merge.autoStash", "true")
    write(store, ITEM, DIRTY); mtime = (store / ITEM).stat().st_mtime_ns
    before = state(store)
    if ident:
        with no_ident():
            if env_ident: os.environ.update(GIT_COMMITTER_NAME=env_ident[0], GIT_COMMITTER_EMAIL=env_ident[1])     # the board's own committer, as the server's process has it
            err = run(P._gitsync, "board: x", "board.md")
    else: err = run(P._gitsync, "board: x", "board.md")
    return dict(origin=origin, store=store, other=other, O1=O1, S1=S1, err=err, before=before, mtime=mtime)
r = disjoint(); st, og = r["store"], r["origin"]; head = git(st, "rev-parse", "HEAD")
check("disjoint: healed and pushed, nothing said", r["err"] == "" and git(og, "rev-parse", "main") == head and head not in (r["O1"], r["S1"]), (r["err"], head))
check("disjoint: the merge has the store's head and the mirror's as its two parents", git(st, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:] == [r["S1"], r["O1"]], git(st, "rev-list", "--parents", "-n", "1", "HEAD"))
check("disjoint: both writers' files are in the mirror's tree and in the working tree", git(og, "show", "main:pages/p.md") == "page, written elsewhere" and git(og, "show", "main:board-data/a.json") == '{"a": 1}' and (st / "pages/p.md").read_text() == "page, written elsewhere\n" and (st / "board-data/a.json").exists())
check("disjoint: the uncommitted item file is as written (content and mtime), the status shows only it, no stash, no rebase",
      (st / ITEM).read_text() == DIRTY and (st / ITEM).stat().st_mtime_ns == r["mtime"] and porcelain(st) == f"M {ITEM}" and git(st, "stash", "list") == "" and not rebased(st), (porcelain(st), git(st, "stash", "list")))
err = run(P._gitsync, "board: x", "board.md")
check("disjoint: a publish after it says nothing and moves nothing", err == "" and git(st, "rev-parse", "HEAD") == head and git(og, "rev-parse", "main") == head, err)
r = disjoint(item_upstream=True); st, og = r["store"], r["origin"]
check("disjoint, dirty overlap: the fast-forward onto the merge is refused, reported once with the file, and nothing moved or pushed",
      len(r["err"].splitlines()) == 1 and r["err"].startswith("publish: fast-forward to the mirror failed: ") and ITEM in r["err"] and state(st) == r["before"] and (st / ITEM).read_text() == DIRTY and git(og, "rev-parse", "main") == r["O1"], r["err"])
r = disjoint(store_cfg=("Store Cfg", "cfg@x"), last_author="Last Author", ident=True)
check("disjoint: the merge is authored by the store clone's configured identity", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Store Cfg <cfg@x> Store Cfg <cfg@x>" and git(r["origin"], "rev-parse", "main") == git(r["store"], "rev-parse", "HEAD"), git(r["store"], "log", "-1", "--format=%an <%ae>"))
r = disjoint(store_cfg=("Store Cfg", "cfg@x"), last_author="Last Author", ident=True, env_ident=("Env Bot", "env.bot@x"))
check("disjoint: the configured identity wins over the committer in the environment, as before", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Store Cfg <cfg@x> Store Cfg <cfg@x>", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>"))
r = disjoint(last_author="Last Author", ident=True)
check("disjoint: with no configured identity and none in the environment, by the committer of the store's last commit", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Last Author <last.author@x> Last Author <last.author@x>" and git(r["origin"], "rev-parse", "main") == git(r["store"], "rev-parse", "HEAD"), (r["err"], git(r["store"], "log", "-1", "--format=%an <%ae>")))
r = disjoint(last_author="Page Author", last_committer="Board Committer", ident=True)
check("disjoint: where the last commit's author is not its committer (a page's), the merge is the committer's, never the author's", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Board Committer <board.committer@x> Board Committer <board.committer@x>" and git(r["origin"], "rev-parse", "main") == git(r["store"], "rev-parse", "HEAD"), (r["err"], git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>")))
r = disjoint(last_author="Page Author", last_committer="Board Committer", ident=True, env_ident=("Env Bot", "env.bot@x"))
check("disjoint: with no configured identity, the committer in the environment (the board's own) makes the merge", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Env Bot <env.bot@x> Env Bot <env.bot@x>", (r["err"], git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>")))

# ============================================================= 3c. a ref that moves while the merge is made: the two heads are read once, nothing is lost
def race_world():
    """A store diverged from the mirror on disjoint files, with an uncommitted item file. Returns (origin, store, other, mirror head, store head)."""
    origin, store, other = world(bulk=3); use(store)
    O1 = commit(other, "pages from elsewhere", **{"pages/p.md": "page, written elsewhere\n"}); git(other, "push", "-q", "origin", "main")
    S1 = commit(store, "store data", **{"board-data/a.json": '{"a": 1}\n'}); write(store, ITEM, DIRTY)
    return origin, store, other, O1, S1
def holds(repo, rev, *names): return all(subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{rev}:{n}"], capture_output=True).returncode == 0 for n in names)
def present(store, origin, *names): return holds(store, "HEAD", *names) and holds(origin, "main", *names) and all((store / n).exists() for n in names)

# P1: a session commits in the shared checkout after the merge-tree call
origin, store, other, O1, S1 = race_world()
def session_commits():
    write(store, "pages/session.md", "a session's page\n"); git(store, "add", "pages/session.md"); git(store, "commit", "-q", "-m", "session")
with wrapped_git(after=session_commits, on="merge-tree"): err = run(P._gitsync, "board: x", "board.md")
check("race, a session commits meanwhile: the session's file is in HEAD's tree and the live tree, and the mirror lost nothing it had", holds(store, "HEAD", "pages/session.md", "board-data/a.json") and (store / "pages/session.md").exists() and holds(origin, "main", "pages/p.md") and (store / ITEM).read_text() == DIRTY, (err, git(store, "log", "--format=%s", "-n", "4")))
check("race, a session commits meanwhile: the merge made from the older head is not taken, nothing pushed, nothing said (the next cycle merges again)", git(origin, "rev-parse", "main") == O1 and err == "" and git(store, "log", "-1", "--format=%s") == "session", (err, git(store, "log", "--format=%s", "-n", "3")))
err = run(P._gitsync, "board: x", "board.md")
check("race, a session commits meanwhile: the next cycle heals it, pushed, and every file is in HEAD, the mirror and the live tree", err == "" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and present(store, origin, "pages/p.md", "pages/session.md", "board-data/a.json") and (store / ITEM).read_text() == DIRTY, (err, git(store, "log", "--graph", "--format=%s", "-n", "5")))

# P2: origin/main moves (another writer's new file arrives by a concurrent fetch) after the merge-tree call
origin, store, other, O1, S1 = race_world()
def mirror_moves():
    git(other, "pull", "-q", "--ff-only", "origin", "main"); commit(other, "more from elsewhere", **{"pages/q.md": "q\n"}); git(other, "push", "-q", "origin", "main"); git(store, "fetch", "-q", "origin", "main")
with wrapped_git(after=mirror_moves, on="merge-tree"): err = run(P._gitsync, "board: x", "board.md")
check("race, the mirror moves meanwhile: the mirror keeps every file it had, and HEAD keeps the store's and the first merge's", holds(origin, "main", "pages/p.md", "pages/q.md") and holds(store, "HEAD", "pages/p.md", "board-data/a.json") and (store / ITEM).read_text() == DIRTY, (err, git(origin, "log", "--format=%s", "-n", "4")))
err = run(P._gitsync, "board: x", "board.md")
check("race, the mirror moves meanwhile: the next cycle heals it, pushed, and every file is in HEAD, the mirror and the live tree", err == "" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and present(store, origin, "pages/p.md", "pages/q.md", "board-data/a.json") and (store / ITEM).read_text() == DIRTY, (err, git(store, "log", "--graph", "--format=%s", "-n", "6")))

# a fast-forward refusal says why in git's own `fatal:` or `error:` line, not in the `hint:` lines before it
origin, store, other = world(bulk=3); use(store)
O1 = commit(other, "mirror side", **{"pages/p.md": "p\n"}); git(other, "push", "-q", "origin", "main"); commit(store, "store side", **{"board-data/a.json": "{}\n"}); git(store, "fetch", "-q", "origin", "main")
reason = P._refused(P._git("merge", "--ff-only", "--quiet", O1))
check("refusal text: a not-descendant fast-forward reads as git's fatal line", reason.startswith("fatal: ") and "hint" not in reason, reason)
check("refusal text: the dirty-overlap refusal names its file after the error line, and a bare stderr reads as its first line", P._refused(subprocess.CompletedProcess([], 1, "", "hint: x\nerror: Your local changes would be overwritten by merge:\n\tboard-data/item-1.json\nAborting\n")) == "error: Your local changes would be overwritten by merge: (board-data/item-1.json)" and P._refused(subprocess.CompletedProcess([], 1, "", "something odd\n")) == "something odd" and P._refused(subprocess.CompletedProcess([], 1, "", "")) == "no reason given")

# ============================================================= 3d. the store clone midway through a session's git operation: the whole step waits, one note an hour
def put_marker(repo, name, dir_=False):
    d = pathlib.Path(git(repo, "rev-parse", "--git-dir")); d = d if d.is_absolute() else pathlib.Path(repo) / d
    (d / name).mkdir() if dir_ else (d / name).write_text(git(repo, "rev-parse", "HEAD") + "\n")
def drop_marker(repo, name, dir_=False):
    d = pathlib.Path(git(repo, "rev-parse", "--git-dir")); d = d if d.is_absolute() else pathlib.Path(repo) / d
    (d / name).rmdir() if dir_ else (d / name).unlink()
def start_rebase(repo):
    env = {"GIT_SEQUENCE_EDITOR": "sed -i '1s/^pick/edit/'", "GIT_EDITOR": "true"}
    os.environ.update(env)
    try: git(repo, "rebase", "-q", "-i", "HEAD~2")
    finally:
        for k in env: os.environ.pop(k, None)
def midway_case(name, words, enter, leave, linked=False):
    origin, store, other = world(bulk=3); use(store)
    commit(other, "mirror side", **{"pages/p.md": "p\n"}); git(other, "push", "-q", "origin", "main")
    commit(store, "store one", **{"board-data/a.json": "{}\n"}); commit(store, "store two", **{"board-data/b.json": "{}\n"})
    repo = store
    if linked: repo = T / f"linked{_n[0]}"; git(store, "switch", "-q", "-c", "park"); git(store, "worktree", "add", "-q", str(repo), "main"); P.REPO = repo
    enter(repo); write(repo, "board.md", "board, to publish\n"); write(repo, ITEM, DIRTY)
    before = state(repo); files = {n: (repo / n).read_bytes() for n in ("board.md", ITEM)}; mirror = git(origin, "rev-parse", "main")
    err = run(P._gitsync, "board: x", "board.md", "board-data")
    check(f"midway, {name}: the live files are byte for byte as they were, HEAD, the refs, the status and the stash list unchanged, nothing published", {n: (repo / n).read_bytes() for n in files} == files and state(repo) == before and git(origin, "rev-parse", "main") == mirror, (state(repo), before))
    check(f"midway, {name}: exactly one note, saying what the clone is in", len(err.splitlines()) == 1 and err.startswith("publish: the store clone is ") and words in err and "waits" in err, err)
    err = run(P._gitsync, "board: x", "board.md", "board-data")
    check(f"midway, {name}: said once an hour", err == "" and state(repo) == before, err)
    git(repo, "checkout", "-q", "--", "."); leave(repo); write(repo, "board.md", "board, to publish\n")
    err = run(P._gitsync, "board: x", "board.md", "board-data")
    check(f"midway, {name}: once it is finished the step runs again (committed, healed and pushed)", err == "" and git(repo, "log", "-1", "--format=%s") != "store two" and git(origin, "rev-parse", "main") == git(repo, "rev-parse", "HEAD") and holds(origin, "main", "pages/p.md", "board-data/a.json", "board-data/b.json"), (err, git(repo, "log", "--format=%s", "-n", "4")))
midway_case("a rebase stopped at edit", "rebase", start_rebase, lambda r: git(r, "rebase", "--abort"))
midway_case("a detached HEAD", "detached HEAD", lambda r: git(r, "checkout", "-q", "--detach"), lambda r: git(r, "switch", "-q", "main"))
midway_case("a merge not concluded", "merge", lambda r: (git(r, "fetch", "-q", "origin", "main"), git(r, "merge", "-q", "--no-commit", "--no-ff", "origin/main")), lambda r: git(r, "merge", "--abort"))
midway_case("a cherry-pick marker", "cherry-pick", lambda r: put_marker(r, "CHERRY_PICK_HEAD"), lambda r: drop_marker(r, "CHERRY_PICK_HEAD"))
midway_case("a revert marker", "revert", lambda r: put_marker(r, "REVERT_HEAD"), lambda r: drop_marker(r, "REVERT_HEAD"))
midway_case("a rebase-apply folder", "rebase", lambda r: put_marker(r, "rebase-apply", True), lambda r: drop_marker(r, "rebase-apply", True))
midway_case("a rebase-merge folder", "rebase", lambda r: put_marker(r, "rebase-merge", True), lambda r: drop_marker(r, "rebase-merge", True))
midway_case("a MERGE_HEAD marker", "merge", lambda r: put_marker(r, "MERGE_HEAD"), lambda r: drop_marker(r, "MERGE_HEAD"))
midway_case("a linked worktree with a rebase folder (its `.git` is a file)", "rebase", lambda r: put_marker(r, "rebase-merge", True), lambda r: drop_marker(r, "rebase-merge", True), linked=True)
# a branch with no commit yet
origin, store, other = world(bulk=3); fresh = T / "unborn"; git(T, "init", "-q", "-b", "main", str(fresh)); git(fresh, "remote", "add", "origin", str(origin)); use(fresh)
write(fresh, "board.md", "board, first\n"); before = (git(fresh, "status", "--porcelain"), git(fresh, "for-each-ref"), git(fresh, "stash", "list")); mirror = git(origin, "rev-parse", "main")
err = run(P._gitsync, "board: x", "board.md")
check("midway, a branch with no commit yet: nothing committed, nothing pushed, the file as written, exactly one note", len(err.splitlines()) == 1 and "no commit yet" in err and (git(fresh, "status", "--porcelain"), git(fresh, "for-each-ref"), git(fresh, "stash", "list")) == before and (fresh / "board.md").read_text() == "board, first\n" and git(origin, "rev-parse", "main") == mirror and subprocess.run(["git", "-C", str(fresh), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode != 0, (err, before))
# a directory that is no repository at all keeps the old behaviour: nothing said by this guard
use(T / "nogit-dir"); (T / "nogit-dir").mkdir(); err = run(P._gitsync, "board: x", "board.md")
check("midway: a folder that is no repository is not called midway", "store clone is" not in err, err)

# a session that commits between the heads being read and the fast-forward (the store behind): no note, nothing lost, the next cycle merges
origin, store, other, O1 = behind_world(overlap=False)
def session_in_the_gap():
    write(store, "pages/session.md", "a session's page\n"); git(store, "add", "pages/session.md"); git(store, "commit", "-q", "-m", "session")
with wrapped_git(after=session_in_the_gap, when=lambda a: a[:2] == ("rev-parse", "--verify") and a[-1] == "origin/main"): err = run(P._gitsync, "board: none", "board.md")
check("behind, a session commits between the read and the merge: no note, the session's file is in HEAD, nothing pushed", err == "" and holds(store, "HEAD", "pages/session.md") and git(origin, "rev-parse", "main") == O1, (err, git(store, "log", "--format=%s", "-n", "3")))
err = run(P._gitsync, "board: none", "board.md")
check("behind, a session commits between the read and the merge: the next cycle merges and pushes, every file present", err == "" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and present(store, origin, "pages/p.md", "pages/session.md"), (err, git(store, "log", "--graph", "--format=%s", "-n", "5")))

# ============================================================= 4. the old step: the same run, caught by the poller
r = diverged(old_gitsync)
check("mutant: with `rebase --autostash` the poller sees the item file read as something else than the uncommitted edit", r["seen"] != {DIRTY}, (r["seen"], r["samples"]))

# ============================================================= 5. a refused push is reported once an hour
origin, store, other = world(bulk=3); use(store)
hook = origin / "hooks/pre-receive"; hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n"); hook.chmod(0o755)
write(store, "board.md", "board, refused\n")
err = run(P._gitsync, "board: refused", "board.md")
check("refused push: one line saying the push was refused, with git's reason", len(err.splitlines()) == 1 and err.startswith("publish: git push was refused: ") and "no pushes today" in err and str(origin) not in err, err)
err = run(P._gitsync, "board: refused", "board.md")
check("refused push: the next publish retries and says nothing within the hour", err == "" and git(origin, "rev-parse", "main") != git(store, "rev-parse", "HEAD"), err)
hook.unlink(); err = run(P._gitsync, "board: refused", "board.md")
check("refused push: once the mirror takes it the commit goes out", git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and err == "", err)

# a reason line that carries an address is skipped, never printed
origin, store, other = world(bulk=3); use(store)
hook = origin / "hooks/pre-receive"; hook.write_text("#!/bin/sh\necho 'see https://example.invalid/policy and git@example.invalid:x/y.git' >&2\necho 'no pushes today' >&2\nexit 1\n"); hook.chmod(0o755)
write(store, "board.md", "board, refused\n"); err = run(P._gitsync, "board: refused", "board.md")
check("refused push: the first reason line without an address is the one said", err.startswith("publish: git push was refused: remote: no pushes today") and "example.invalid" not in err and "http" not in err and str(origin) not in err, err)
hook.write_text("#!/bin/sh\necho 'see https://example.invalid/policy' >&2\nexit 1\n"); P._NOTED.clear(); err = run(P._gitsync, "board: refused", "board.md")
check("refused push: a mirror whose only reason line is an address says no address", len(err.splitlines()) == 1 and "example.invalid" not in err and "http" not in err and str(origin) not in err, err)
check("refused push: no usable line reads as no reason given", P._why(subprocess.CompletedProcess([], 1, "", "remote: https://example.invalid/x\nTo /somewhere/origin.git\n")) == "no reason given")

# a non-fast-forward rejection (another writer pushed between the fetch and the push) is reported with its reason
origin, store, other = world(bulk=3); use(store)
write(store, "board.md", "board, raced\n")
def race(): commit(other, "raced ahead", **{"pages/p.md": "p\n"}); git(other, "push", "-q", "origin", "main")
with wrapped_git(after=race): err = run(P._gitsync, "board: raced", "board.md")
check("non-fast-forward: one line, the push was refused and the ref's rejection is the reason", len(err.splitlines()) == 1 and err.startswith("publish: git push was refused: ") and "rejected]" in err and ("non-fast-forward" in err or "fetch first" in err), err)
err = run(P._gitsync, "board: raced", "board.md")
check("non-fast-forward: the next publish heals it without a note", err == "" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and (store / "pages/p.md").exists(), err)

# the merge note and the push note are separate kinds: one said does not silence the other (the process-wide record is kept across the worlds)
def refused_push_world():
    origin, store, other = world(bulk=3); P.REPO = store
    hook = origin / "hooks/pre-receive"; hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n"); hook.chmod(0o755)
    write(store, "board.md", "board, refused\n"); return run(P._gitsync, "board: refused", "board.md")
P._NOTED.clear(); err = refused_push_world()
check("kinds: a push refusal is said", "git push was refused" in err and "no pushes today" in err, err)
origin, store, other, O1 = behind_world(keep_notes=True)           # the push note is in the record now
err = run(P._gitsync, "board: none", "board.md")
check("kinds: a merge refusal is said although the push refusal was said just before", "fast-forward to the mirror failed" in err and ITEM in err, err)
P._NOTED.clear(); run(P._note, "merge", "publish: a merge note, said earlier")
err = refused_push_world()
check("kinds: a push refusal is said although a merge note was said just before", "git push was refused" in err and "no pushes today" in err, err)

# ============================================================= 5b. what the step does before it knows where origin stands
# a failed fetch returns at once: the stale refs are never acted on (the push URL works here, so a step that went on would push)
origin, store, other = world(bulk=3); use(store)
git(store, "config", "remote.origin.pushurl", str(origin)); git(store, "config", "remote.origin.url", str(T / "no-such-mirror.git"))
write(store, "board.md", "board, no fetch\n"); mirror = git(origin, "rev-parse", "main")
err = run(P._gitsync, "board: no fetch", "board.md")
check("failed fetch: committed locally, nothing pushed, nothing said", git(store, "log", "-1", "--format=%s") == "board: no fetch" and git(origin, "rev-parse", "main") == mirror and err == "", err)

# a quiet publish never contacts the mirror
origin, store, other = world(bulk=3); use(store); calls = []
with wrapped_git(calls=calls): err = run(P._gitsync, "board: quiet", "board.md", "board-data")
check("quiet publish: nothing committed, nothing ahead: no fetch, no push, nothing said", err == "" and not any(c[:1] in (("fetch",), ("push",)) for c in calls), (calls, err))

# `commit --only`: a file a session staged and the publisher does not own stays out of the publish commit and stays staged
origin, store, other = world(bulk=3); use(store)
write(store, "session.txt", "a session's own file\n"); git(store, "add", "session.txt"); write(store, "board.md", "board, own\n")
err = run(P._gitsync, "board: own", "board.md")
check("commit --only: the publish commit holds the board file only, the session's file is still staged", git(store, "show", "--name-only", "--format=", "HEAD") == "board.md" and porcelain(store) == "A  session.txt" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), (git(store, "show", "--name-only", "--format=", "HEAD"), porcelain(store)))

# git cannot compare the refs (origin/main missing though the fetch passed): said as an error of its own, never as a divergence
origin, store, other = world(bulk=3); use(store)
git(store, "update-ref", "-d", "refs/remotes/origin/main"); git(store, "config", "remote.origin.fetch", "+refs/heads/none:refs/remotes/origin/none")
write(store, "board.md", "board, no ref\n"); mirror = git(origin, "rev-parse", "main")
err = run(P._gitsync, "board: no ref", "board.md")
check("no ref: one line naming git's exit status, not a divergence; nothing pushed", len(err.splitlines()) == 1 and "could not read" in err and "exit 128" in err and "diverged" not in err and git(origin, "rev-parse", "main") == mirror, err)

# ============================================================= 5c. `publish.py flush` against a conflicted mirror exits non-zero with the note
def frepo(name, pages=False):
    """A data repository the publisher itself runs in (its own config file): (repo, bare mirror, another writer's clone, config path).
    `pages`: write `[publish] pages = true` into its config; left out (the default), the config keeps the example's `pages = false`, i.e. off."""
    fr = T / f"{name}-repo"; fo = T / f"{name}-origin.git"; git(T, "init", "-q", "--bare", "-b", "main", str(fo)); git(T, "clone", "-q", str(fo), str(fr))
    commit(fr, "first", **{"board.md": "board\n", "board-data/README": "data\n"}); git(fr, "branch", "-M", "main"); git(fr, "push", "-q", "-u", "origin", "main")
    fother = T / f"{name}-other"; git(T, "clone", "-q", str(fo), str(fother))
    ft = toml.replace(f'repo = "{tmp}"', f'repo = "{fr}"', 1).replace(f'store = "{tmp}/store"', f'store = "{fr}/board-data"', 1).replace(f'markdown = "{tmp}/board.md"', f'markdown = "{fr}/board.md"', 1)
    assert ft.count(str(fr)) == 3
    if pages: ft = pages_toml(ft)
    (T / f"{name}.toml").write_text(ft, encoding="utf-8")
    return fr, fo, fother, T / f"{name}.toml"
def flush(cfg):
    env = {**os.environ, "STACKSHOT_CONFIG": str(cfg), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(pathlib.Path(STACK, "stackshot/web/publish.py")), "flush"], capture_output=True, text=True, env=env, cwd=STACK, timeout=300)
FR, fo, fother, fcfg = frepo("flush")
f = flush(fcfg)
check("flush: a healthy store is committed and pushed, exit 0", f.returncode == 0 and "committed and pushed" in f.stdout and git(fo, "rev-parse", "main") == git(FR, "rev-parse", "HEAD"), (f.returncode, f.stdout[-300:], f.stderr[-600:]))
git(fother, "pull", "-q", "--ff-only", "origin", "main"); commit(fother, "elsewhere", **{"board-data/README": "data, from elsewhere\n"}); git(fother, "push", "-q", "origin", "main")
commit(FR, "store's own", **{"board-data/README": "data, from the store\n"}); before = state(FR); mirror = git(fo, "rev-parse", "main")
f = flush(fcfg)
check("flush: against a conflicted mirror it exits non-zero, says it left the store, and pushes nothing", f.returncode != 0 and "diverged and conflict" in f.stderr and "not flushed" in f.stderr and git(fo, "rev-parse", "main") == mirror, (f.returncode, f.stdout[-300:], f.stderr[-800:]))
check("flush: the conflicted store got no merge commit and no rebase, its tree has no conflict markers", git(FR, "rev-list", "--merges", "--count", "HEAD") == "0" and not rebased(FR) and "<<<<<<<" not in (FR / "board-data/README").read_text(), git(FR, "log", "--format=%s", "-n", "4"))

# ============================================================= 5d. `merge.autoStash = true` in the store's own config: no fast-forward the publisher runs stashes, pops or leaves markers
def untouched(repo, text=DIRTY): return (repo / ITEM).read_bytes() == text.encode() and git(repo, "stash", "list") == "" and "<<<<<<<" not in (repo / ITEM).read_text() and ">>>>>>>" not in (repo / ITEM).read_text()
origin, store, other, O1 = behind_world(); git(store, "config", "merge.autoStash", "true"); before = state(store)
err = run(P._gitsync, "board: none", "board.md")
check("autostash, behind: the item file is byte for byte as written, no stash, no markers, nothing moved, one note naming the file", untouched(store) and state(store) == before and len(err.splitlines()) == 1 and ITEM in err and "fast-forward to the mirror failed" in err, (err, git(store, "stash", "list")))
r = disjoint(item_upstream=True, autostash=True)
check("autostash, diverged on disjoint files: the item file is byte for byte as written, no stash, no markers, nothing moved or pushed, one note naming the file", untouched(r["store"]) and state(r["store"]) == r["before"] and git(r["origin"], "rev-parse", "main") == r["O1"] and len(r["err"].splitlines()) == 1 and ITEM in r["err"], (r["err"], git(r["store"], "stash", "list")))
# the fast-forward at the top of `publish()` itself (run as the flush does), in a repository that has the edit on a file the mirror changed
AR, ao, aother, acfg = frepo("autostash"); f = flush(acfg)
check("autostash, top of publish(): a healthy store flushes (control)", f.returncode == 0, (f.returncode, f.stdout[-200:], f.stderr[-400:]))
NOTE = "notes/note.md"                        # a tracked file outside what the publisher commits, so its edit stays uncommitted through the publish
git(aother, "pull", "-q", "--ff-only", "origin", "main"); commit(aother, "a page", **{NOTE: "page\n"}); git(aother, "push", "-q", "origin", "main"); git(AR, "pull", "-q", "--ff-only", "origin", "main")
commit(aother, "the page, from elsewhere", **{NOTE: "page, from elsewhere\n"}); git(aother, "push", "-q", "origin", "main")
(AR / NOTE).write_text("page, edited in the store\n"); git(AR, "config", "merge.autoStash", "true"); before = state(AR)
f = flush(acfg); page = (AR / NOTE).read_text()
check("autostash, top of publish(): the edited file is byte for byte as written, no stash, no markers, HEAD unmoved", page == "page, edited in the store\n" and git(AR, "stash", "list") == "" and git(AR, "rev-parse", "HEAD") == before[0], (page, git(AR, "stash", "list"), f.stderr[-400:]))

# the fast-forward at the top of `publish()` waits as well while the clone is on a detached HEAD
MR, mo, mother, mcfg = frepo("midway"); f = flush(mcfg)
check("midway, top of publish(): a healthy store flushes (control)", f.returncode == 0, (f.returncode, f.stdout[-200:], f.stderr[-400:]))
git(mother, "pull", "-q", "--ff-only", "origin", "main"); commit(mother, "elsewhere", **{"pages/p.md": "p\n"}); git(mother, "push", "-q", "origin", "main")
git(MR, "checkout", "-q", "--detach"); before = state(MR); f = flush(mcfg)
check("midway, top of publish(): a detached HEAD is not fast-forwarded, the files unchanged, one note", state(MR) == before and not (MR / "pages/p.md").exists() and f.stderr.count("the store clone is on a detached HEAD") == 1, (state(MR), before, f.stderr[-400:]))

# the single read: the merge check gets the two heads as read once, never their names, and no later step names them
origin, store, other, O1, S1 = race_world(); calls = []
with wrapped_git(calls=calls): err = run(P._gitsync, "board: x", "board.md")
mt = [c for c in calls if c[:1] == ("merge-tree",)]; after = calls[next(i for i, c in enumerate(calls) if c[:2] == ("rev-parse", "--verify")):]
check("single read: merge-tree is called with the two commits read once, and no step after the reads names HEAD or origin/main again", mt == [("merge-tree", "--write-tree", S1, O1)] and not [c for c in after if c[:1] in (("merge-base",), ("merge-tree",), ("rev-list",), ("merge",)) and ({"HEAD", "origin/main"} & set(c))], (mt, calls))

origin, store, other, O1 = behind_world(); calls = []
with wrapped_git(calls=calls): err = run(P._gitsync, "board: none", "board.md")
check("single read: the fast-forward of a store that is behind goes to the commit read once, not to the name", [c for c in calls if c[:1] == ("merge",)] == [("merge", "--ff-only", "--no-autostash", "--quiet", O1)], calls)

# ============================================================= 5e. a brain's pages: publish_pages() commits the files it is named, nothing else, ever
P._SERVING = True
BOT = "Board Bot"
@contextlib.contextmanager
def as_bot(mail=True):
    """The board's identity as the committer, and no author in the environment: what the server's process has. mail=False: the committer's name only."""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    os.environ.update(GIT_COMMITTER_NAME=BOT, **({"GIT_COMMITTER_EMAIL": "bot@x"} if mail else {}))
    try: yield
    finally:
        for k in ("GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"): os.environ.pop(k, None)
        os.environ.update(saved)
@contextlib.contextmanager
def pages_on():
    """[publish] pages on: the only state in which publish_pages() commits anything."""
    real = P._pages_on; P._pages_on = lambda: True
    try: yield
    finally: P._pages_on = real
def who(repo, rev="HEAD"): return git(repo, "log", "-1", "--format=%an|%cn|%s", rev).split("|", 2)
def count(repo): return int(git(repo, "rev-list", "--count", "HEAD"))
def pages_toml(text):
    out, n = re.subn(r'(?m)^pages = false\b', 'pages = true', text, count=1); assert n == 1, "no `pages = false` line under [publish] in the example config"
    return out
def staged(repo): return git(repo, "diff", "--cached", "--name-only")
def names(repo, rev="HEAD"): return git(repo, "show", "--name-only", "--format=", rev).splitlines()
def put(paths, author="Ada Example", email="", mail=True):
    """publish_pages() with the switch on, as the board's bot: ("ok", what it returned), ("failed", CommitFailed's words), ("type", TypeError's) or
    ("raised", any other Exception's name and words: never what publish_pages() may raise for a page)."""
    with pages_on(), as_bot(mail):
        try: return ("ok", P.publish_pages(paths, author, email))
        except P.CommitFailed as e: return ("failed", str(e))
        except TypeError as e: return ("type", str(e))
        except Exception as e: return ("raised", f"{type(e).__name__}: {e}")
def sub(a):
    """The git subcommand of a call's arguments, past the global options (--literal-pathspecs, -c <key>=<value>)."""
    i = 0
    while i < len(a) and a[i].startswith("-"): i += 2 if a[i] == "-c" else 1
    return a[i] if i < len(a) else ""
STAGING = ("add", "rm", "commit", "reset", "update-index", "read-tree")
def staged_any(calls): return [c for c in calls if sub(c) in STAGING]
def refused_early(paths, author="Ada Example", email="", mail=True):
    """A put that must be refused before git is asked to stage anything: (result, the staging calls made, HEAD moved, something staged)."""
    calls = []; head = git(P.REPO, "rev-parse", "HEAD")
    with wrapped_git(calls=calls): got = put(paths, author, email, mail)
    return got, staged_any(calls), git(P.REPO, "rev-parse", "HEAD") != head, staged(P.REPO)
PG = "pages/ada-note.md"

# off by default: publish_pages() raises and nothing under pages/ is touched, whatever a session left there
origin, store, other = world(bulk=2); use(store); n0 = count(store)
write(store, PG, "# untouched\n"); write(store, "pages/.env", "SECRET=1\n"); write(store, "pages/note.md.swp", "swap\n")
git(store, "add", "pages/note.md.swp")      # a session's own half-finished `git add`, not a commit
head0 = git(store, "rev-parse", "HEAD"); por0 = porcelain(store)
with as_bot():
    try: P.publish_pages(["ada-note.md"], "Ada Example"); off = "returned"
    except P.CommitFailed as e: off = str(e)
check("pages: with [publish] pages as the example config sets it (false, the default) publish_pages() raises, says the switch is off, and touches nothing", "off" in off and count(store) == n0 and git(store, "rev-parse", "HEAD") == head0 and porcelain(store) == por0, (off, porcelain(store)))
real_on = P._git_on; P._git_on = lambda: False
try: got = put(["ada-note.md"])
finally: P._git_on = real_on
check("pages: with [publish] git off it raises too, and commits and pushes nothing", got[0] == "failed" and git(store, "rev-parse", "HEAD") == head0 and git(origin, "rev-parse", "main") == head0, got)
saved_cfg = P._cfg.CFG; seen = {}
try:
    for v in ("false", "true", 1, True, False):
        P._cfg.CFG = {**saved_cfg, "publish": {**(saved_cfg.get("publish") or {}), "pages": v}}; seen[repr(v)] = P._pages_on()
    P._cfg.CFG = {k: v for k, v in saved_cfg.items() if k != "publish"}; seen["unset"] = P._pages_on()
finally: P._cfg.CFG = saved_cfg
check("pages: only a TOML true turns [publish] pages on (the string \"false\", the string \"true\" and 1 do not)", seen == {"'false'": False, "'true'": False, "1": False, "True": True, "False": False, "unset": False}, seen)

# one put: one commit of the named file, the person as author, the bot as committer, pushed; nothing else
origin, store, other = world(bulk=2); use(store); n0 = count(store)
write(store, PG, "# note\n"); write(store, "board.md", "board, changed\n"); write(store, "pages/other.md", "not named\n")
got = put(["ada-note.md"])
check("pages: a put makes exactly one commit and returns True", got == ("ok", True) and count(store) == n0 + 1, (got, count(store), n0))
check("pages: the commit names the person as author and the board's bot as committer, and the page in its message", who(store) == ["Ada Example", BOT, "board: page ada-note.md"], who(store))
check("pages: the commit carries the named page and nothing else, and it is pushed", names(store) == [PG] and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), names(store))
check("pages: what the put did not name stays as it was, uncommitted (board.md, another page)", "M board.md" in porcelain(store) and "?? pages/other.md" in porcelain(store), porcelain(store))
git(store, "checkout", "-q", "--", "board.md"); (store / "pages/other.md").unlink()
git(other, "pull", "-q", "--ff-only", "origin", "main"); commit(other, "elsewhere", **{"notes/e.md": "e\n"}); git(other, "push", "-q", "origin", "main")
head = git(store, "rev-parse", "HEAD"); got = put(["ada-note.md"])
check("pages: an unchanged page returns False and makes no commit, no merge with the mirror's newer commit, no push", got == ("ok", False) and git(store, "rev-parse", "HEAD") == head, (got, git(store, "log", "-2", "--format=%s")))
write(store, PG, "# note, edited\n"); got = put([pathlib.PurePosixPath("ada-note.md")])
check("pages: a path given as a path object names its file too, and the page goes out with the mirror's newer commit merged", got == ("ok", True) and git(origin, "show", f"main:{PG}") == "# note, edited" and holds(origin, "main", "notes/e.md") and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), got)

# authors: cleaned or refused before anything is staged; the address never the clone's own
write(store, PG, "# note, third\n"); got = put(["ada-note.md"], "Mallory <evil@x>\nSigned-off-by: x")
check("pages: a name with angle brackets or a line break is one name on the commit", got == ("ok", True) and who(store)[0] == "Mallory evil@x Signed-off-by: x", (got, who(store)))
write(store, PG, "# note, fourth\n"); got = put(["ada-note.md"], "Weird\x00Name" + "\udc80" + "X" * 400)
check("pages: a NUL byte, a lone surrogate and an over-long name are cleaned, not raised, and make one clean commit", got == ("ok", True) and who(store)[0].startswith("Weird Name X") and len(who(store)[0]) <= P._NAME_LIMIT and porcelain(store) == "", (got, who(store)))
write(store, PG, "# note, fifth\n")
for bad in ("", ".", "...", "\x7f", " , ; : ", "<>", "\x00\n", None):
    got, calls, moved, st = refused_early(["ada-note.md"], bad)
    check(f"pages: the author {bad!r} is refused before git is asked to stage anything, nothing moved, nothing staged", got[0] == "failed" and "author" in got[1] and not calls and not moved and st == "", (got, calls, st))
check("pages: the page of a refused author is still uncommitted on disk, as written", porcelain(store) == f"M {PG}", porcelain(store))
got = put(["ada-note.md"], "Grace Example", "  <grace\n.example@x>\x00 ")
check("pages: the address is cleaned of angle brackets, white space and control characters", got == ("ok", True) and git(store, "log", "-1", "--format=%an <%ae>") == "Grace Example <grace.example@x>", (got, git(store, "log", "-1", "--format=%an <%ae>")))
write(store, PG, "# note, sixth\n"); got = put(["ada-note.md"], "Grace Example", "...")
check("pages: an address that cleans to nothing falls back to the board's own (GIT_COMMITTER_EMAIL)", got == ("ok", True) and git(store, "log", "-1", "--format=%ae") == "bot@x", (got, git(store, "log", "-1", "--format=%ae")))
git(store, "config", "user.email", "clone-owner@x")
write(store, PG, "# note, seventh\n"); got = put(["ada-note.md"], "Grace Example", mail=False)
check("pages: with no address given and none in the environment, the author's is the generic one, never the clone's configured user.email", got == ("ok", True) and git(store, "log", "-1", "--format=%ae|%ce") == "board@localhost|clone-owner@x", (got, git(store, "log", "-1", "--format=%ae|%ce")))
write(store, PG, "# note, eighth\n"); got = put(["ada-note.md"], "Grace Example")
check("pages: nor does it win over the board's own address in the environment", got == ("ok", True) and git(store, "log", "-1", "--format=%ae") == "bot@x", git(store, "log", "-1", "--format=%ae"))
git(store, "config", "--unset", "user.email")
write(store, PG, "# note, no committer\n"); got, calls, moved, st = refused_early(["ada-note.md"], mail=False)
check("pages: a board with no committer address git accepts (none in the environment or the clone) is refused before anything is staged", got[0] == "failed" and "committer" in got[1] and not calls and not moved and st == "", (got, calls, st))

# paths: anything that could reach outside pages/, act as a pattern or name more than one file is refused before anything is staged
write(store, "secret.txt", "outside\n"); write(store, "board.md", "board, dirty\n"); write(store, ITEM, DIRTY); write(store, PG, "# note, ninth\n")
before = porcelain(store)
for bad in ("../secret.txt", "..", "../board.md", "../board-data", "../board-data/item-1.json", ".", "./ada-note.md", "x/../ada-note.md", "/ada-note.md",
            "x//ada-note.md", "ada-note.md/", "", "ada\x00note.md", "ada\nnote.md", "ada\x7fnote.md", "ada\x85note.md", "ada\x9fnote.md", "caf\udce9.md"):
    for paths in ([bad], ["ada-note.md", bad]):
        got, calls, moved, st = refused_early(paths)
        check(f"pages: the path list {paths!r} is refused before git is asked to stage anything, nothing moved, nothing staged", got[0] == "failed" and not calls and not moved and st == "", (got, calls, st))
head_c1 = git(store, "rev-parse", "HEAD")
for c1 in ("\x85", "\x9f"):          # a name that exists on disk (the loop above names files that are not there) and holds a C1 control character
    write(store, f"pages/ada{c1}note.md", "c1\n"); got = put([f"ada{c1}note.md"]); (store / f"pages/ada{c1}note.md").unlink()
    check(f"pages: a path holding the C1 control character U+{ord(c1):04X} that exists on disk is refused, nothing committed", got[0] == "failed" and git(store, "rev-parse", "HEAD") == head_c1 and staged(store) == "", got)
check("pages: after every refusal the working tree is exactly as it was (the outside files untouched, the named page uncommitted)", porcelain(store) == before, (porcelain(store), before))
for whole in ("ada-note.md", b"ada-note.md", pathlib.PurePosixPath("ada-note.md")):
    got, calls, moved, st = refused_early(whole)
    check(f"pages: one {type(whole).__name__} where a list is meant raises TypeError, nothing staged", got[0] == "type" and not calls and not moved and st == "", got)
got, calls, moved, st = refused_early([])
check("pages: an empty list is refused, nothing staged", got[0] == "failed" and not calls and not moved, got)
got, calls, moved, st = refused_early([7])
check("pages: a path that is no text raises TypeError, nothing staged", got[0] == "type" and not calls and not moved, got)
git(store, "checkout", "-q", "--", "board.md", ITEM); (store / "secret.txt").unlink(); git(store, "checkout", "-q", "--", PG)
write(store, "pages/a[1].md", "literal\n"); write(store, "pages/a1.md", "the pattern's match\n"); write(store, "pages/q?.md", "literal\n"); write(store, "pages/qx.md", "the pattern's match\n")
got = put(["a[1].md", "q?.md"])
check("pages: a path is a file name, never a pattern: a[1].md and q?.md commit themselves, never a1.md or qx.md", got == ("ok", True) and sorted(names(store)) == ["pages/a[1].md", "pages/q?.md"] and "?? pages/a1.md" in porcelain(store) and "?? pages/qx.md" in porcelain(store), (got, names(store), porcelain(store)))
for bad in ("*", "a?.md", "q*", ":(glob)*.md", ":/board.md"):
    got, calls, moved, st = refused_early([bad])
    check(f"pages: the path {bad!r} names no file of its own and is refused before anything is staged, the files it would match left alone", got[0] == "failed" and not moved and st == "" and "?? pages/a1.md" in porcelain(store), (got, calls, st))
(store / "pages/a1.md").unlink(); (store / "pages/qx.md").unlink()
write(store, "pages/notes/x.md", "x\n"); write(store, "pages/notes/y.md", "y\n"); got = put(["notes/x.md", "notes/y.md"])
check("pages: files in a folder under pages/ commit as named", got == ("ok", True) and sorted(names(store)) == ["pages/notes/x.md", "pages/notes/y.md"], got)
write(store, "pages/notes/x.md", "x, edited\n")
got, calls, moved, st = refused_early(["notes"])
check("pages: a folder is refused (one path, one file), nothing staged", got[0] == "failed" and "not a file" in got[1] and not calls and not moved, got)
shutil.rmtree(store / "pages/notes")
got, calls, moved, st = refused_early(["notes"])
check("pages: a folder gone from disk is refused too, never read as the removal of everything in it", got[0] == "failed" and not moved and holds(store, "HEAD", "pages/notes/x.md", "pages/notes/y.md") and st == "", (got, st))
git(store, "checkout", "-q", "--", "pages/notes")
for bad in ("nope.md", "pages/ada-note.md"):
    got, calls, moved, st = refused_early([bad])
    check(f"pages: {bad!r}, neither on disk nor in the last commit (a typo, a doubled pages/), raises instead of returning False", got[0] == "failed" and "neither" in got[1] and not calls and not moved, got)

# links: a page that is a link, a folder that is one, and pages/ itself as one are refused; nothing is read as removed
outside = T / "outside-secret.txt"; outside.write_text("outside\n")
(store / "pages/link.md").symlink_to(outside)
got, calls, moved, st = refused_early(["link.md"])
check("pages: a page file that is a symbolic link (here to a file outside the repository) is refused, nothing staged", got[0] == "failed" and "link" in got[1] and not calls and not moved, got)
(store / "pages/link.md").unlink()
(T / "elsewhere").mkdir(exist_ok=True); write(T, "elsewhere/x.md", "elsewhere\n"); (store / "pages/sub").symlink_to(T / "elsewhere")
got, calls, moved, st = refused_early(["sub/x.md"])
check("pages: a path through a folder that is a symbolic link is refused, nothing staged", got[0] == "failed" and "pages/sub" in got[1] and not calls and not moved, got)
(store / "pages/sub").unlink()
tracked = git(store, "ls-tree", "-r", "--name-only", "HEAD", "--", "pages").splitlines()
(store / "pages").rename(store / "pages-real"); (store / "pages").symlink_to(store / "pages-real")
got, calls, moved, st = refused_early(["ada-note.md"])
check("pages: pages/ itself a symbolic link is refused, nothing staged, every page still in HEAD", got[0] == "failed" and not calls and not moved and git(store, "ls-tree", "-r", "--name-only", "HEAD", "--", "pages").splitlines() == tracked, got)
(store / "pages").unlink(); (store / "pages-real").rename(store / "pages")

# the folder missing or emptied: only the files named are removed, never the rest
(store / "pages").rename(store / "pages-moved")
got, calls, moved, st = refused_early(["."])
check("pages: \".\" with pages/ gone is refused, nothing staged, nothing removed", got[0] == "failed" and not calls and not moved and st == "", got)
got = put(["ada-note.md"])
left = git(store, "ls-tree", "-r", "--name-only", "HEAD", "--", "pages").splitlines()
check("pages: with pages/ moved away, the named page's removal is the only one committed; every other page stays in HEAD and the mirror", got == ("ok", True) and names(store) == [PG] and sorted(left) == sorted(t for t in tracked if t != PG) and holds(origin, "main", *left), (got, names(store), left))
(store / "pages-moved").rename(store / "pages"); git(store, "checkout", "-q", "HEAD~1", "--", PG); got = put(["ada-note.md"])
check("pages: written again, the page is back in one commit", got == ("ok", True) and holds(origin, "main", PG), got)

# the last page removed, its folder gone from disk: committed, not stuck
origin, store, other = world(bulk=2); use(store)
write(store, "pages/only.md", "only\n"); got = put(["only.md"])
(store / "pages/only.md").unlink(); (store / "pages").rmdir(); got2 = put(["only.md"])
check("pages: the last page removed with its folder gone is committed as one removal, pushed, nothing left over", got == ("ok", True) and got2 == ("ok", True) and names(store) == ["pages/only.md"] and not holds(origin, "main", "pages/only.md") and porcelain(store) == "", (got, got2, porcelain(store)))
got = put(["only.md"])
check("pages: naming it again, once its removal is committed, raises (neither on disk nor in the last commit) rather than reading as unchanged", got[0] == "failed" and "neither" in got[1], got)
write(store, "pages/gone.md", "g\n"); put(["gone.md"]); (store / "pages/gone.md").unlink(); git(store, "rm", "-q", "--cached", "pages/gone.md")
got = put(["gone.md"])
check("pages: a removal already staged by someone else (no index entry left) still commits as the named removal", got == ("ok", True) and names(store) == ["pages/gone.md"] and not holds(store, "HEAD", "pages/gone.md"), got)

# a file and a folder that swapped places: it goes out with both sides named, never with a file the caller did not name
origin, store, other = world(bulk=2); use(store)
write(store, "pages/notes/x.md", "x\n"); write(store, "pages/notes/y.md", "y\n"); put(["notes/x.md", "notes/y.md"]); head = git(store, "rev-parse", "HEAD")
shutil.rmtree(store / "pages/notes"); write(store, "pages/notes", "notes, a file now\n")
got = put(["notes"])
check("pages, swap: a folder that became a file, named alone, raises (its files would go with it), HEAD unmoved, nothing left staged, its files still in the index",
      got[0] == "failed" and "pages/notes/x.md" in got[1] and "name both sides" in got[1] and git(store, "rev-parse", "HEAD") == head and staged(store) == "" and git(store, "ls-files", "--", "pages/notes").splitlines() == ["pages/notes/x.md", "pages/notes/y.md"], (got, staged(store)))
got, calls, moved, st = refused_early(["notes/x.md"])
check("pages, swap: a file of that folder named alone is refused before anything is staged (the folder is a file now and not named)", got[0] == "failed" and "not a folder" in got[1] and not calls and not moved and st == "", got)
hook = store / ".git/hooks/pre-commit"; hook.write_text("#!/bin/sh\necho 'not now' >&2\nexit 1\n"); hook.chmod(0o755)
try: got = put(["notes", "notes/x.md", "notes/y.md"])
finally: hook.unlink()
check("pages, swap: both sides named and a commit hook that refuses: CommitFailed, nothing left staged (the removals of the folder's files included)", got[0] == "failed" and "git commit failed" in got[1] and staged(store) == "" and git(store, "rev-parse", "HEAD") == head, (got, staged(store)))
got = put(["notes", "notes/x.md", "notes/y.md"])
check("pages, swap: both sides named: one commit of the new file and the folder's files' removal, pushed, nothing left over", got == ("ok", True) and sorted(names(store)) == ["pages/notes", "pages/notes/x.md", "pages/notes/y.md"] and git(origin, "show", "main:pages/notes") == "notes, a file now" and not holds(origin, "main", "pages/notes/x.md") and porcelain(store) == "", (got, names(store), porcelain(store)))
(store / "pages/notes").unlink(); write(store, "pages/notes/z.md", "z\n"); head = git(store, "rev-parse", "HEAD")
got = put(["notes/z.md"])
check("pages, swap: a file that became a folder, only the file in it named, raises (the old file would go with it), HEAD unmoved, nothing left staged, the old file still in the index",
      got[0] == "failed" and "pages/notes would go with" in got[1] and git(store, "rev-parse", "HEAD") == head and staged(store) == "" and git(store, "ls-files", "--", "pages/notes") == "pages/notes", (got, staged(store)))
got, calls, moved, st = refused_early(["notes"])
check("pages, swap: that folder named alone is refused before anything is staged (one path, one file)", got[0] == "failed" and "not a file" in got[1] and not calls and not moved and st == "", got)
got = put(["notes", "notes/z.md"])
check("pages, swap: both sides named: one commit of the old file's removal and the new file in the folder, pushed, nothing left over", got == ("ok", True) and sorted(names(store)) == ["pages/notes", "pages/notes/z.md"] and git(origin, "show", "main:pages/notes/z.md") == "z" and porcelain(store) == "", (got, names(store), porcelain(store)))

# a .git part, a folder that is a repository of its own, a folder that cannot be read, an unmerged page, an entry marked assume-unchanged: never False
write(store, "pages/.GIT/x.md", "x\n"); write(store, "pages/a/.Git", "x\n")      # on disk, so that nothing but the part itself refuses them
for bad in (".git/config", "sub/.git/HEAD", ".GIT/x.md", "a/.Git"):
    got, calls, moved, st = refused_early([bad])
    check(f"pages: {bad!r} (a .git part) is refused before anything is staged", got[0] == "failed" and ".git" in got[1] and not calls and not moved and st == "", got)
shutil.rmtree(store / "pages/.GIT"); shutil.rmtree(store / "pages/a")
(store / "pages/inner").mkdir(); git(store / "pages/inner", "init", "-q"); write(store, "pages/inner/x.md", "x\n")
got, calls, moved, st = refused_early(["inner/x.md"])
check("pages: a page in a folder that is a repository of its own is refused before anything is staged", got[0] == "failed" and "pages/inner is a git repository of its own" in got[1] and not calls and not moved, got)
shutil.rmtree(store / "pages/inner"); git(store / "pages", "init", "-q"); write(store, PG, "# in a nested pages\n")
got, calls, moved, st = refused_early(["ada-note.md"])
check("pages: pages/ itself a repository of its own is refused before anything is staged", got[0] == "failed" and "pages is a git repository of its own" in got[1] and not calls and not moved, got)
shutil.rmtree(store / "pages/.git")
write(store, "pages/locked/a.md", "a\n"); put(["locked/a.md"]); head = git(store, "rev-parse", "HEAD")
os.chmod(store / "pages/locked", 0)
try:
    unreadable = not os.access(store / "pages/locked/a.md", os.F_OK)       # root reads it all the same
    got = put(["locked/a.md"]) if unreadable else None
finally: os.chmod(store / "pages/locked", 0o755)
if unreadable:
    check("pages: a tracked page in a folder that cannot be read raises, never read as its removal; HEAD unmoved, the page still in HEAD, nothing staged", got[0] == "failed" and "cannot be read" in got[1] and git(store, "rev-parse", "HEAD") == head and holds(store, "HEAD", "pages/locked/a.md") and staged(store) == "", (got, staged(store)))
else: print("note: run as root, the folder that cannot be read is read all the same: that check is skipped")
write(store, PG, "# base\n"); put(["ada-note.md"])
write(store, PG, "# mine, stashed\n"); git(store, "stash", "push", "-q", "-m", "fixture-stash", "--", PG)
write(store, PG, "# theirs, committed\n"); put(["ada-note.md"]); head = git(store, "rev-parse", "HEAD")
git(store, "stash", "pop", "-q", ok=False); unm0 = git(store, "ls-files", "-u")
got, calls, moved, st = refused_early(["ada-note.md"])
check("pages: a page a stash pop left unmerged (conflict markers in it) is refused before anything is staged, HEAD unmoved, the conflict left as it was", got[0] == "failed" and "unmerged" in got[1] and not calls and not moved and unm0 != "" and git(store, "ls-files", "-u") == unm0, (got, calls, unm0))
git(store, "checkout", "-q", "HEAD", "--", PG); git(store, "stash", "drop", "-q")
write(store, PG, "# assume\n"); put(["ada-note.md"]); head = git(store, "rev-parse", "HEAD")
git(store, "update-index", "--assume-unchanged", PG); write(store, PG, "# assume, edited\n")
got = put(["ada-note.md"])
check("pages: an edited page whose entry in the store clone's index is marked assume-unchanged is committed as it is on disk (the commit's own index has no such mark), never False; that index brought to it",
      got == ("ok", True) and git(store, "show", f"HEAD:{PG}") == "# assume, edited" and who(store)[0] == "Ada Example" and git(store, "diff", "--cached", "--name-only", "HEAD") == "", (got, git(store, "ls-files", "-v", "--", PG)))
git(store, "update-index", "--no-assume-unchanged", PG)

# the clone midway through a session's git operation: raises, never "unchanged"; once it is finished the same author's retry commits
for name, words, enter, leave in (("a detached HEAD", "detached HEAD", lambda r: git(r, "checkout", "-q", "--detach"), lambda r: git(r, "switch", "-q", "main")),
                                  ("a merge not concluded", "merge", lambda r: (git(r, "fetch", "-q", "origin", "main"), git(r, "merge", "-q", "--no-commit", "--no-ff", "origin/main")), lambda r: git(r, "merge", "--abort")),
                                  ("a rebase-merge folder", "rebase", lambda r: put_marker(r, "rebase-merge", True), lambda r: drop_marker(r, "rebase-merge", True))):
    origin, store, other = world(bulk=2); use(store)
    commit(other, "mirror side", **{"notes/m.md": "m\n"}); git(other, "push", "-q", "origin", "main")
    enter(store); write(store, PG, f"# {name}\n"); head = git(store, "rev-parse", "HEAD"); st0 = staged(store)
    got = put(["ada-note.md"])
    check(f"pages, midway ({name}): raises saying what the clone is in, HEAD unmoved, nothing staged, nothing pushed", got[0] == "failed" and words in got[1] and git(store, "rev-parse", "HEAD") == head and staged(store) == st0 and not holds(origin, "main", PG), (got, staged(store)))
    leave(store); got = put(["ada-note.md"])
    check(f"pages, midway ({name}): once it is finished the same author's retry commits and pushes", got == ("ok", True) and who(store, git(store, "log", "-1", "--format=%H", "--", PG))[0] == "Ada Example" and holds(origin, "main", PG), (got, git(store, "log", "-3", "--format=%an %s")))

# git refusing a step: CommitFailed, nothing left staged, never swept up later by the board's publish or another author; the same author's retry commits
origin, store, other = world(bulk=2); use(store)
write(store, PG, "# locked\n"); lockfile = store / ".git" / "index.lock"; lockfile.write_text(""); head = git(store, "rev-parse", "HEAD")
try: got, calls, moved, st = refused_early(["ada-note.md"])
finally: lockfile.unlink(missing_ok=True)
check("pages: a held index.lock raises CommitFailed before anything is staged or committed, not a silent False, and says the index is locked", got[0] == "failed" and "index.lock" in got[1] and "locked" in got[1] and not calls and not moved and st == "", (got, calls, st))
write(store, "board.md", "board, after the failure\n"); write(store, "pages/grace.md", "grace\n")
err = run(P._gitsync, "board: after", "board.md", "board-data")
check("pages: the board's own publish after a failed put commits the board only, never the failed page", names(store) == ["board.md"] and not holds(store, "HEAD", PG), names(store))
got = put(["grace.md"], "Grace Example")
check("pages: another author's put after a failed one commits that author's page only, never the failed page", got == ("ok", True) and names(store) == ["pages/grace.md"] and not holds(store, "HEAD", PG), (got, names(store)))
got = put(["ada-note.md"])
check("pages: the same author's retry, the lock gone, commits the page under that author and pushes it", got == ("ok", True) and names(store) == [PG] and who(store)[0] == "Ada Example" and holds(origin, "main", PG), got)
write(store, PG, "# sign-fail\n"); git(store, "config", "commit.gpgsign", "true"); git(store, "config", "gpg.program", "false"); head = git(store, "rev-parse", "HEAD")
try: got = put(["ada-note.md"])
finally: git(store, "config", "--unset", "commit.gpgsign"); git(store, "config", "--unset", "gpg.program")
check("pages: a refusal at the commit itself (a failed sign) raises too, HEAD unmoved, nothing left staged", got[0] == "failed" and "git commit failed" in got[1] and git(store, "rev-parse", "HEAD") == head and staged(store) == "", (got, staged(store)))
got = put(["ada-note.md"])
check("pages: once signing is off again, the same author's retry commits", got == ("ok", True) and who(store)[0] == "Ada Example", got)
# an add that staged every path and then reported a failure: none of them staged in the store clone's index, its bytes as they were
write(store, "pages/good.md", "good\n"); write(store, "pages/bad.md", "bad\n"); head = git(store, "rev-parse", "HEAD"); real_git = P._git
def add_fails_after(*a, **k):
    r = real_git(*a, **k)
    return subprocess.CompletedProcess(a, 1, "", "fatal: simulated add failure\n") if sub(a) == "add" else r
P._git = add_fails_after; idx0 = (store / ".git/index").read_bytes()
try: got = put(["good.md", "bad.md"])
finally: P._git = real_git
check("pages: an add that fails after staging leaves none of the named paths staged, the store clone's index byte for byte as it was", got[0] == "failed" and "simulated" in got[1] and (store / ".git/index").read_bytes() == idx0 and staged(store) == "" and git(store, "rev-parse", "HEAD") == head, (got, staged(store)))
# the store clone's index held by another git right after the commit (a post-commit hook that takes its lock): the commit stays made (True), and stderr says what is left and how to clear it
hook = store / ".git/hooks/post-commit"; hook.write_text("#!/bin/sh\n: > .git/index.lock\n"); hook.chmod(0o755); errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf): got = put(["good.md", "bad.md"])
finally: hook.unlink(); (store / ".git/index.lock").unlink(missing_ok=True)
left = git(store, "diff", "--cached", "--name-only", "HEAD")
check("pages: the store clone's index locked right after the commit: True, the commit made under its author, and stderr says the index could not be brought to it, names the files and how to clear them",
      got == ("ok", True) and who(store)[0] == "Ada Example" and sorted(names(store)) == ["pages/bad.md", "pages/good.md"] and "could not be brought" in errbuf.getvalue() and "pages/good.md" in errbuf.getvalue() and "git reset -q --" in errbuf.getvalue() and sorted(left.splitlines()) == ["pages/bad.md", "pages/good.md"], (got, errbuf.getvalue(), left))
git(store, "reset", "-q", "--", "pages/good.md", "pages/bad.md")
check("pages: ...and the line's own words clear it: nothing staged after `git reset -q -- <the files>`", staged(store) == "", staged(store))
write(store, "pages/good.md", "good, again\n"); write(store, "pages/bad.md", "bad, again\n")
got = put(["good.md", "bad.md"])
check("pages: two pages named in one put make one commit of both", got == ("ok", True) and sorted(names(store)) == ["pages/bad.md", "pages/good.md"] and who(store)[2] == "board: page good.md, bad.md", (got, names(store), who(store)))

# a refused push: the commit is made (True) under its author, said once, and the next publish pushes it
origin, store, other = world(bulk=2); use(store)
hook = origin / "hooks/pre-receive"; hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n"); hook.chmod(0o755)
write(store, PG, "# pushed later\n"); errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
check("pages: a refused push leaves the commit made (True), its author on it, the refusal said", got == ("ok", True) and who(store)[0] == "Ada Example" and not holds(origin, "main", PG) and "push was refused" in errbuf.getvalue(), (got, errbuf.getvalue()))
hook.unlink(); err = run(P._gitsync, "board: x", "board.md")
check("pages: the next publish pushes it", holds(origin, "main", PG) and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), err)

# git's words in bytes that are not UTF-8, git that cannot be started, an interrupt, the push step failing: never a raise with something left staged
origin, store, other = world(bulk=2); use(store); real_git = P._git
hook = store / ".git/hooks/pre-commit"; hook.write_bytes(b"#!/bin/sh\nprintf 'refused \\377\\376 here\\n' >&2\nexit 1\n"); hook.chmod(0o755)
write(store, PG, "# hook\n"); head = git(store, "rev-parse", "HEAD")
try: got = put(["ada-note.md"])
finally: hook.unlink()
check("pages: a commit hook that refuses in bytes that are not UTF-8: CommitFailed with its words, nothing staged, HEAD unmoved", got[0] == "failed" and "git commit failed: refused" in got[1] and staged(store) == "" and git(store, "rev-parse", "HEAD") == head, (got, staged(store)))
def step_raises(*a, **k):
    if sub(a) == "commit": raise OSError(7, "Argument list too long")
    return real_git(*a, **k)
P._git = step_raises
try: got = put(["ada-note.md"])
finally: P._git = real_git
check("pages: git that cannot be started at the commit (an OSError) raises CommitFailed, not the OSError, nothing staged, HEAD unmoved", got[0] == "failed" and "OSError" in got[1] and staged(store) == "" and git(store, "rev-parse", "HEAD") == head, (got, staged(store)))
rhook = origin / "hooks/pre-receive"; rhook.write_bytes(b"#!/bin/sh\nprintf 'no \\377 pushes\\n' >&2\nexit 1\n"); rhook.chmod(0o755); errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
finally: rhook.unlink()
check("pages: a push refused in bytes that are not UTF-8: the commit is made (True) under its author, the refusal said, nothing raised", got == ("ok", True) and who(store)[0] == "Ada Example" and not holds(origin, "main", PG) and "push was refused" in errbuf.getvalue(), (got, errbuf.getvalue()))
real_sync = P._gitsync
def sync_raises(*a, **k): raise OSError(12, "Cannot allocate memory")
P._gitsync = sync_raises; write(store, PG, "# sync fails\n"); errbuf = io.StringIO()
try:
    with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
finally: P._gitsync = real_sync
check("pages: the push step raising after the commit is said on stderr, and the commit made is True", got == ("ok", True) and "push step after it failed" in errbuf.getvalue() and git(store, "show", f"HEAD:{PG}") == "# sync fails", (got, errbuf.getvalue()))
got, calls, moved, st = refused_early([f"{'p' * 200}-{i}.md" for i in range(12000)])
check("pages: 12,000 long paths raise CommitFailed (name them over several calls) before anything is staged, never an OSError", got[0] == "failed" and "several calls" in got[1] and not calls and not moved and st == "", (got[0], got[1][:200], calls[:1]))
got, calls, moved, st = refused_early(["n" * 5000 + ".md"])
check("pages: a path longer than the system takes raises CommitFailed (cannot be read) before anything is staged", got[0] == "failed" and "cannot be read" in got[1] and not calls and not moved, got)
for i in range(P._PATHS_MAX): write(store, f"pages/many/{i}.md", f"{i}\n")
got = put([f"many/{i}.md" for i in range(P._PATHS_MAX)])
check(f"pages: {P._PATHS_MAX} paths, the most one call takes, make one commit", got == ("ok", True) and len(names(store)) == P._PATHS_MAX and who(store)[2] == f"board: {P._PATHS_MAX} pages", (got, len(names(store))))
got, calls, moved, st = refused_early([f"many/{i}.md" for i in range(P._PATHS_MAX + 1)])
check("pages: one path more is refused before anything is staged", got[0] == "failed" and "several calls" in got[1] and not calls and not moved, got)

# a branch with no upstream: a put commits and pushes to the mirror's main all the same, and an unchanged page is False
origin, store, other = world(bulk=2); use(store); git(store, "branch", "--unset-upstream")
write(store, PG, "# no upstream\n"); got = put(["ada-note.md"])
check("pages: on a branch with no upstream a put commits (True) and pushes it to the mirror's main", got == ("ok", True) and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and holds(origin, "main", PG), got)
head = git(store, "rev-parse", "HEAD"); got = put(["ada-note.md"])
check("pages: on it, the same page again is False, nothing moved", got == ("ok", False) and git(store, "rev-parse", "HEAD") == head, got)

# the mirror out of reach (the fetch before the push fails, which the push step passes over in silence): the commit is True, and stderr says it is not out yet
origin, store, other = world(bulk=2); use(store); git(store, "remote", "set-url", "origin", str(T / "no-such-mirror.git"))
write(store, PG, "# mirror away\n"); errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
check("pages: the mirror out of reach: True, the commit made under its author, and stderr says it is not on the mirror yet", got == ("ok", True) and who(store)[0] == "Ada Example" and "not on the mirror yet" in errbuf.getvalue(), (got, errbuf.getvalue()))
git(store, "remote", "set-url", "origin", str(origin)); err = run(P._gitsync, "board: x", "board.md")
check("pages: ...and the mirror back, the next publish (the branch tracks it) pushes it", holds(origin, "main", PG) and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), err)

# [paths] repo a folder inside the repository rather than its top: refused, never False with the page staged
origin, store, other = world(bulk=2); write(store, "sub/pages/x.md", "below the top\n"); use(store / "sub")
got, calls, moved, st = refused_early(["x.md"])
check("pages: [paths] repo a folder inside its repository, not the top: refused before anything is staged, saying so", got[0] == "failed" and "not the repository's top" in got[1] and not calls and not moved and st == "", (got, calls, st))

# the store clone's index, which every session on the host shares: what a session staged there is never dropped, unstaged or committed by a put
def idx(repo): return (repo / ".git/index").read_bytes()
origin, store, other = world(bulk=2); use(store)
commit(store, "pages to swap", **{"pages/n/old.md": "old\n", "pages/q/a.md": "qa\n", "pages/f": "f, a file\n", "pages/r/x.md": "x\n", "pages/r/y.md": "y\n", "pages/e.md": "e\n"}); git(store, "push", "-q", "origin", "main")
write(store, "pages/n/z.md", "a session's new file\n"); git(store, "add", "pages/n/z.md")
shutil.rmtree(store / "pages/n"); write(store, "pages/n", "n, a file now\n"); i0 = idx(store); head = git(store, "rev-parse", "HEAD")
got = put(["n", "n/old.md"])
check("pages, a session's staging: a folder that became a file, both sides named, while a session has a new file staged in that folder: refused naming that file, HEAD and the mirror unmoved, the index byte for byte as it was",
      got[0] == "failed" and "pages/n/z.md" in got[1] and "would be dropped" in got[1] and git(store, "rev-parse", "HEAD") == head and git(origin, "rev-parse", "main") == head and idx(store) == i0, (got, staged(store)))
git(store, "rm", "-q", "--cached", "--ignore-unmatch", "pages/n/z.md"); got = put(["n", "n/old.md"])
check("pages, a session's staging: that file unstaged, the same put commits both sides", got == ("ok", True) and sorted(names(store)) == ["pages/n", "pages/n/old.md"] and staged(store) == "", (got, names(store), staged(store)))
git(store, "rm", "-r", "-q", "--cached", "pages/q"); shutil.rmtree(store / "pages/q"); write(store, "pages/q", "q, a session's file\n"); git(store, "add", "pages/q")
(store / "pages/q").unlink(); write(store, "pages/q/new.md", "new\n"); i0 = idx(store); head = git(store, "rev-parse", "HEAD")
got = put(["q/new.md"])
check("pages, a session's staging: a session's staged file where a named page needs a folder (the reverse): refused naming it, HEAD unmoved, the index byte for byte as it was",
      got[0] == "failed" and "pages/q," in got[1] and "would be dropped" in got[1] and git(store, "rev-parse", "HEAD") == head and idx(store) == i0, (got, staged(store)))
git(store, "reset", "-q", "--", "pages/q", ok=False); (store / "pages/q/new.md").unlink(missing_ok=True); git(store, "checkout", "-q", "HEAD", "--", "pages/q", ok=False)
(store / "pages/f").unlink(); write(store, "pages/f/x.md", "x, the page\n"); write(store, "pages/f/w.md", "w, a session's\n"); git(store, "add", "pages/f/w.md")
got = put(["f", "f/x.md"])
check("pages, a session's staging: a file that became a folder, both sides named, with a session's new file staged in that folder: committed, the session's file not in the commit and still staged",
      got == ("ok", True) and sorted(names(store)) == ["pages/f", "pages/f/x.md"] and not holds(store, "HEAD", "pages/f/w.md") and staged(store) == "pages/f/w.md", (got, names(store), staged(store)))
git(store, "rm", "-q", "--cached", "--ignore-unmatch", "pages/f/w.md"); (store / "pages/f/w.md").unlink()
write(store, "notes/s.md", "a session's new file\n"); write(store, "board.md", "board, a session's staged edit\n"); git(store, "add", "notes/s.md", "board.md")
write(store, PG, "# beside a session's staged files\n"); got = put(["ada-note.md"])
check("pages, a session's staging: files a session staged outside pages/ (a new one, an edit) stay out of the commit and stay staged as they were",
      got == ("ok", True) and names(store) == [PG] and sorted(staged(store).splitlines()) == ["board.md", "notes/s.md"] and git(store, "show", ":board.md") == "board, a session's staged edit", (got, names(store), staged(store)))
git(store, "reset", "-q", "--", "notes/s.md", "board.md", ok=False); git(store, "checkout", "-q", "HEAD", "--", "board.md"); (store / "notes/s.md").unlink()
git(store, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "pages/r"); write(store, "pages/r/x.md", "x, a session's edit\n"); git(store, "add", "pages/r/x.md")
git(store, "rm", "-q", "--ignore-unmatch", "pages/e.md"); write(store, "pages/r/y.md", "y, the page\n")
hook = store / ".git/hooks/pre-commit"; hook.write_text("#!/bin/sh\necho 'not now' >&2\nexit 1\n"); hook.chmod(0o755)
i0 = idx(store); st0 = git(store, "diff", "--cached", "--name-status"); head = git(store, "rev-parse", "HEAD")
try: got1 = put(["r/y.md"]); got2 = put(["e.md"])
finally: hook.unlink()
check("pages, a session's staging: puts that fail (a refusing hook) under a session's staged removal of a folder with an edit staged in it, and its staged removal of a page: the index byte for byte as it was",
      all(g[0] == "failed" and "git commit failed" in g[1] for g in (got1, got2)) and idx(store) == i0 and git(store, "diff", "--cached", "--name-status") == st0 and git(store, "rev-parse", "HEAD") == head, (got1, got2, st0, git(store, "diff", "--cached", "--name-status")))
got = put(["r/y.md", "e.md"])
check("pages, a session's staging: the hook gone, the put commits the named pages only, and the session's staged edit is still staged as it was",
      got == ("ok", True) and sorted(names(store)) == ["pages/e.md", "pages/r/y.md"] and git(store, "show", ":pages/r/x.md") == "x, a session's edit" and git(store, "diff", "--cached", "--name-only") == "pages/r/x.md", (got, names(store), staged(store)))

# a submodule under a folder that became a file: never removed unnamed, whatever the config tells git to hide
origin, store, other = world(bulk=2); use(store)
write(store, "pages/a/x.md", "x\n"); write(store, ".gitmodules", '[submodule "s"]\n\tpath = pages/a/sub\n\turl = ./nowhere\n\tignore = all\n')
git(store, "add", "pages/a/x.md", ".gitmodules"); git(store, "update-index", "--add", "--cacheinfo", f"160000,{git(store, 'rev-parse', 'HEAD')},pages/a/sub")
git(store, *SEED, "commit", "-q", "-m", "a submodule under pages"); git(store, "push", "-q", "origin", "main"); git(store, "config", "diff.ignoreSubmodules", "all")
shutil.rmtree(store / "pages/a"); write(store, "pages/a", "a, a file now\n"); head = git(store, "rev-parse", "HEAD")
got = put(["a", "a/x.md"])
check("pages, submodule: a folder holding a submodule became a file, both named, with .gitmodules ignore=all and diff.ignoreSubmodules=all: refused naming the submodule, HEAD and the mirror unmoved, the submodule still in HEAD",
      got[0] == "failed" and "pages/a/sub" in got[1] and "would go with" in got[1] and git(store, "rev-parse", "HEAD") == head and git(origin, "rev-parse", "main") == head and git(store, "ls-tree", "HEAD", "--", "pages/a/sub").startswith("160000"), got)

# no automatic maintenance from the page commit: its gc would read the commit's own index, not the store clone's, and prune a blob only a session's staged entry holds
origin, store, other = world(bulk=2); use(store)
for k, v in (("gc.autoPackLimit", "1"), ("gc.autoDetach", "false"), ("maintenance.autoDetach", "false")): git(store, "config", k, v)
git(store, "repack", "-d", "-q"); commit(store, "a second pack", **{"notes/p.md": "p\n"}); git(store, "repack", "-d", "-q")
blob = subprocess.run(["git", "-C", str(store), "hash-object", "-w", "--stdin"], input="a session's staged file, a month old\n", capture_output=True, text=True).stdout.strip()
git(store, "update-index", "--add", "--cacheinfo", f"100644,{blob},notes/old-staged.txt")
month = time.time() - 30 * 86400; os.utime(store / ".git/objects" / blob[:2] / blob[2:], (month, month))
write(store, PG, "# beside an old staged blob\n"); got = put(["ada-note.md"])
check("pages: a month-old blob only a session's staged entry holds is still there after a put (two packs, gc.autoPackLimit 1), and still staged",
      got == ("ok", True) and subprocess.run(["git", "-C", str(store), "cat-file", "-e", blob]).returncode == 0 and git(store, "ls-files", "-s", "--", "notes/old-staged.txt").split()[1:2] == [blob], got)

# an interrupt (SIGINT to the publisher alone, git left running) while git commits: git ends as it would, nothing of its left behind, and the interrupt is said
CHILD = ("import pathlib, signal, sys\nsys.path.insert(0, sys.argv[1])\nfrom stackshot.web import publish as P\n"
         "signal.signal(signal.SIGINT, signal.default_int_handler)\n"            # as a process started from a terminal has it, whatever this test inherited (a runner may ignore SIGINT)
         "P.REPO = pathlib.Path(sys.argv[2]); P._SERVING = True; P._pages_on = lambda: True\n"
         "try: print('returned', P.publish_pages([sys.argv[3]], 'Ada Example'))\n"
         "except KeyboardInterrupt as e: print('interrupt', e); sys.exit(3)\n")
def own_child(proc):
    """Whether `proc` (this test's own Popen child, not yet waited for) is still the python this test started: only then is it signalled, by its PID."""
    try: return proc.poll() is None and os.path.realpath(f"/proc/{proc.pid}/exe") == os.path.realpath(sys.executable)
    except OSError: return False
def interrupted(store, code, hook_name="pre-commit", group=False):
    """publish_pages() of PG in a child process of this test's own, sent SIGINT by its PID while git runs the pre-commit hook, which waits 2 s and exits
    `code`. `group`: the signal goes to the child's whole process group, as a terminal's Ctrl-C does (the child leads its own group). (the child's exit code, its stdout and stderr, what its TMPDIR holds after it, whether the hook ran)."""
    ready = T / f"ready-{hook_name}-{code}"; tmpd = T / f"child-tmp-{hook_name}-{code}"; tmpd.mkdir()
    hook = store / ".git/hooks" / hook_name; hook.write_text(f"#!/bin/sh\n: > {shlex.quote(str(ready))}\nsleep 2\nexit {code}\n"); hook.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    env.update(GIT_COMMITTER_NAME=BOT, GIT_COMMITTER_EMAIL="bot@x", TMPDIR=str(tmpd), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, "-c", CHILD, STACK, str(store), "ada-note.md"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=STACK, start_new_session=group)
    try:
        t0 = time.monotonic()
        while proc.poll() is None and not ready.exists() and time.monotonic() - t0 < 120: time.sleep(0.02)
        if ready.exists() and own_child(proc): (os.killpg if group else os.kill)(proc.pid, signal.SIGINT)
        out, err = proc.communicate(timeout=300)
    finally:
        if own_child(proc): os.kill(proc.pid, signal.SIGKILL)
        if proc.returncode is None: proc.communicate()
        hook.unlink(missing_ok=True)
    return proc.returncode, out, err, sorted(os.listdir(tmpd)), ready.exists()
def git_left(store): return sorted(p.name for p in (store / ".git").iterdir() if p.name == "index.lock" or p.name.startswith("next-index"))
origin, store, other = world(bulk=2); use(store); head = git(store, "rev-parse", "HEAD")
write(store, PG, "# interrupted, made\n"); rc, out, err, left, ran_hook = interrupted(store, 0)
check("pages, interrupt: SIGINT while git commits (its hook passes): git finishes, the commit made under its author, the index brought to it, nothing pushed, KeyboardInterrupt saying so",
      ran_hook and rc == 3 and "interrupted; the page commit is made" in err and "interrupted; the page commit is made" in out and git(store, "rev-parse", "HEAD") != head and who(store)[0] == "Ada Example" and names(store) == [PG] and staged(store) == "" and not holds(origin, "main", PG), (rc, out[-300:], err[-600:]))
check("pages, interrupt: ...no index.lock or next-index lock of git's left in the store clone, nothing left in TMPDIR", git_left(store) == [] and left == [], (git_left(store), left))
err2 = run(P._gitsync, "board: x", "board.md")
check("pages, interrupt: ...and the next publish pushes it", holds(origin, "main", PG) and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), err2)
write(store, PG, "# interrupted, refused\n"); head = git(store, "rev-parse", "HEAD"); i0 = idx(store)
rc, out, err, left, ran_hook = interrupted(store, 1)
check("pages, interrupt: SIGINT while git commits (its hook refuses): KeyboardInterrupt saying no page commit was made and why, HEAD unmoved, the index byte for byte as it was, no lock of git's left, nothing left in TMPDIR",
      ran_hook and rc == 3 and "interrupted; no page commit made" in err and "git commit failed" in err and git(store, "rev-parse", "HEAD") == head and idx(store) == i0 and git_left(store) == [] and left == [], (rc, out[-300:], err[-600:], git_left(store), left))
got = put(["ada-note.md"])
check("pages, interrupt: ...and the same author's next put commits and pushes it", got == ("ok", True) and who(store)[0] == "Ada Example" and holds(origin, "main", PG), got)

# Ctrl-C of a terminal goes to the whole process group, git and its hooks included: a slow post-commit hook runs on, the commit made is reported as made
write(store, PG, "# interrupted by the group\n"); head = git(store, "rev-parse", "HEAD")
rc, out, err, left, ran_hook = interrupted(store, 0, "post-commit", group=True)
check("pages, interrupt: SIGINT to the whole group while a post-commit hook runs: git is not stopped, the commit is made, the index brought to it, KeyboardInterrupt saying so",
      ran_hook and rc == 3 and "interrupted; the page commit is made" in err and git(store, "rev-parse", "HEAD") != head and names(store) == [PG] and staged(store) == "" and git_left(store) == [] and left == [], (rc, out[-300:], err[-600:], git_left(store), left))

# git's commit ends non-zero after the ref moved (a killed git can do that): the commit is made, not "nothing committed"
real_git = P._git
def moved_then_fails(*a, **k):
    r = real_git(*a, **k)
    if "commit" in a and "--only" in a and r.returncode == 0:
        return subprocess.CompletedProcess(r.args, 1, r.stdout, "fatal: killed after the ref moved\n")
    return r
write(store, PG, "# killed after the ref moved\n"); head = git(store, "rev-parse", "HEAD")
P._git = moved_then_fails
try: got = put(["ada-note.md"])
finally: P._git = real_git
check("pages: a git commit that fails after HEAD moved is a commit made: True, the index brought to it, no page left staged", got == ("ok", True) and git(store, "rev-parse", "HEAD") != head and staged(store) == "" and git(store, "show", f"HEAD:{PG}") == "# killed after the ref moved", (got, staged(store)))

# no room for the call's own folder: CommitFailed, never a bare OSError
real_mkdtemp = tempfile.mkdtemp
def no_room(*a, **k): raise OSError(28, "No space left on device")
write(store, PG, "# no room\n"); head = git(store, "rev-parse", "HEAD"); tempfile.mkdtemp = no_room
try: got = put(["ada-note.md"])
finally: tempfile.mkdtemp = real_mkdtemp
check("pages: no room for the temporary folder raises CommitFailed saying nothing was committed", got[0] == "failed" and "nothing" in got[1] and git(store, "rev-parse", "HEAD") == head and staged(store) == "", got)

# git cannot be started right after the commit (the first git call once the index is brought to it): the commit is made, the call returns True, said on stderr
def gone_after(*a, **k):
    if a[:2] == ("rev-parse", "HEAD") and gone_after.armed: raise BlockingIOError(11, "Resource temporarily unavailable")
    return real_git(*a, **k)
gone_after.armed = False
orig_bring = P._bring_index
def bring_then_arm(*a, **k): r = orig_bring(*a, **k); gone_after.armed = True; return r
write(store, PG, "# git gone after\n"); errbuf = io.StringIO()
P._git = gone_after; P._bring_index = bring_then_arm
try:
    with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
finally: P._git = real_git; P._bring_index = orig_bring; gone_after.armed = False
check("pages: git failing to start after the commit is said, and the commit made is True", got == ("ok", True) and "push step after it failed" in errbuf.getvalue() and git(store, "show", f"HEAD:{PG}") == "# git gone after", (got, errbuf.getvalue()[-300:]))

# a clone on another branch: the note says the push is of main only
git(store, "checkout", "-q", "-b", "side"); write(store, PG, "# on a side branch\n"); errbuf = io.StringIO()
with contextlib.redirect_stderr(errbuf): got = put(["ada-note.md"])
git(store, "checkout", "-q", "main")
check("pages: a page committed on a branch other than main is True, and the note names the branch and says the push is of main only", got == ("ok", True) and "on side" in errbuf.getvalue() and "main only" in errbuf.getvalue(), (got, errbuf.getvalue()[-400:]))

# the board's merge with the mirror after a page commit, on a clone with no configured identity: the board's own, never the page's author
origin, store, other = world(bulk=2); use(store)
commit(other, "elsewhere", **{"notes/e.md": "e\n"}); git(other, "push", "-q", "origin", "main")
write(store, PG, "# merged after\n"); got = put(["ada-note.md"])
merge = git(store, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%P").split("|")
check("pages: a put on a diverged clone with no configured identity: the page is the person's, the merge after it is the board's (author and committer), pushed",
      got == ("ok", True) and merge[:2] == [f"{BOT} <bot@x>", f"{BOT} <bot@x>"] and len(merge[2].split()) == 2 and who(store, "HEAD^1")[0] == "Ada Example" and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD"), (got, merge))

# a page file whose name is not UTF-8 is refused by name, and stops nothing else
origin, store, other = world(bulk=2); use(store)
(store / "pages").mkdir(); bad_name = os.path.join(os.fsencode(str(store)), b"pages", b"caf\xe9.md")
with open(bad_name, "wb") as fh: fh.write(b"not utf-8 named\n")
got, calls, moved, st = refused_early([os.fsdecode(b"caf\xe9.md")])
check("pages: a page whose file name is not UTF-8 is refused before anything is staged", got[0] == "failed" and not calls and not moved, got)
write(store, PG, "# beside it\n"); got = put(["ada-note.md"]); write(store, "board.md", "board, beside it\n"); err = run(P._gitsync, "board: beside", "board.md", "board-data")
check("pages: beside such a file a page put and the board's publish both go out as usual", got == ("ok", True) and holds(origin, "main", PG) and git(origin, "show", "main:board.md") == "board, beside it" and err == "", (got, err))

# the standby guard: publish_pages() refuses on a read-only copy, same as the rest of the publisher, and writes nothing
origin, store, other = world(bulk=2); use(store)
write(store, PG, "# standby\n"); head = git(store, "rev-parse", "HEAD")
P._ro._reload_for_test(True)
try:
    with pages_on(), as_bot():
        try: P.publish_pages(["ada-note.md"], "Ada Example"); raised_ro = False
        except P._ro.ReadOnlyError: raised_ro = True
finally: P._ro._reload_for_test()          # back to what the environment says (off here)
check("pages: publish_pages() refuses on a read-only standby, writing nothing", raised_ro and git(store, "rev-parse", "HEAD") == head and porcelain(store) == "?? pages/", (raised_ro, porcelain(store)))

# the lock: across processes (the flock), across threads, and nested in one thread
def try_flock():
    """Whether another holder could take the publish flock right now (a descriptor of this test's own, so it competes like another process)."""
    with open(P.LOCK, "a") as fh:
        try: fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
        fcntl.flock(fh, fcntl.LOCK_UN); return True
origin, store, other = world(bulk=2); use(store); P.LOCK.parent.mkdir(parents=True, exist_ok=True)
write(store, PG, "# waits\n"); head = git(store, "rev-parse", "HEAD"); box = {}
holder = open(P.LOCK, "a"); fcntl.flock(holder, fcntl.LOCK_EX)
th = threading.Thread(target=lambda: box.update(got=put(["ada-note.md"])), daemon=True)
try:
    th.start(); th.join(2.0); waited = th.is_alive() and git(store, "rev-parse", "HEAD") == head
finally: fcntl.flock(holder, fcntl.LOCK_UN); holder.close()
th.join(120)
check("lock: publish_pages() waits while another process holds the publish flock, and commits once it is let go", waited and box.get("got") == ("ok", True), (waited, box))
inside = threading.Event(); leave_ = threading.Event(); box = {}
def hold():
    with P.pages_lock(): inside.set(); leave_.wait(60)
th = threading.Thread(target=hold, daemon=True); th.start(); inside.wait(30)
write(store, PG, "# second\n"); head = git(store, "rev-parse", "HEAD")
th2 = threading.Thread(target=lambda: box.update(got=put(["ada-note.md"])), daemon=True); th2.start(); th2.join(2.0)
held = not try_flock(); blocked = th2.is_alive() and git(store, "rev-parse", "HEAD") == head
leave_.set(); th.join(30); th2.join(120)
check("lock: pages_lock() holds the cross-process flock, and another thread's put waits for it", held and blocked and box.get("got") == ("ok", True), (held, blocked, box))
check("lock: let go, the flock is free again", try_flock())
box = {}
def nested():
    with P.pages_lock():
        write(store, PG, "# nested\n")
        box["got"] = put(["ada-note.md"])
        box["held_after_inner"] = not try_flock()
    box["free_after_outer"] = try_flock()
th = threading.Thread(target=nested, daemon=True); th.start(); th.join(60)
check("lock: publish_pages() inside pages_lock() nests (no wait on itself), the outer hold keeps the flock after the inner one ends, and lets it go at its own end",
      not th.is_alive() and box.get("got") == ("ok", True) and box.get("held_after_inner") is True and box.get("free_after_outer") is True, box)
if th.is_alive():                    # the nested hold waits on itself: the lock stays taken for good and every later check would wait on it, so stop here
    print(f"FAILED: publish_git scenario, {len(ran)} checks, {len(fails)} failed (stopped: the publish lock waits on itself)"); sys.exit(1)

# a race on one page under pages_lock(): each commit's content is its own author's write
origin, store, other = world(bulk=2); use(store); race_start = git(store, "rev-parse", "HEAD"); errors = []
WRITERS, ROUNDS = 4, 4
def same_page(i):
    for w in range(ROUNDS):
        with P.pages_lock():
            write(store, "pages/shared.md", f"Writer{i} round {w}\n")
            try: P.publish_pages(["shared.md"], f"Writer{i}")
            except P.CommitFailed as e: errors.append(str(e))
ths = [threading.Thread(target=same_page, args=(i,)) for i in range(WRITERS)]
with pages_on(), as_bot():          # the switch and the environment once, around every writer: threads never change os.environ under each other
    for t in ths: t.start()
    for t in ths: t.join(300)
shas = git(store, "rev-list", f"{race_start}..HEAD", "--", "pages/shared.md").split()
mismatch = [s for s in shas if not git(store, "show", f"{s}:pages/shared.md").startswith(git(store, "log", "-1", "--format=%an", s) + " ")]
check("lock: four writers on one page, under pages_lock(): every commit's content is its own author's write, none skipped", not errors and not mismatch and len(shas) == WRITERS * ROUNDS, (errors, mismatch[:3], len(shas)))
# six writers on six pages, each naming its own: never a swapped author
origin, store, other = world(bulk=2); use(store); race_start = git(store, "rev-parse", "HEAD"); errors = []
def own_page(i):
    for w in range(5):
        with P.pages_lock():
            write(store, f"pages/race-{i}.md", f"Writer{i} write {w}\n")
            try: P.publish_pages([f"race-{i}.md"], f"Writer{i}")
            except P.CommitFailed as e: errors.append(str(e))
ths = [threading.Thread(target=own_page, args=(i,)) for i in range(6)]
with pages_on(), as_bot():          # the switch and the environment once, around every writer: threads never change os.environ under each other
    for t in ths: t.start()
    for t in ths: t.join(300)
log = git(store, "log", "--format=%an|%s", f"{race_start}..HEAD").splitlines()
wrong = [l for l in log if l.split("|")[1] != f"board: page race-{l.split('|')[0].removeprefix('Writer')}.md"]
check("lock: six writers on six pages: every commit's page is its own author's, none swapped, none skipped", not errors and not wrong and len(log) == 30, (errors, wrong[:5], len(log)))
check("lock: each writer's last write is the one on the mirror", all(git(origin, "show", f"main:pages/race-{i}.md") == f"Writer{i} write 4" for i in range(6)))

# two boards, two repositories: a put in one pushes to its own mirror only
oA, sA, _ = world(bulk=2); oB, sB, _ = world(bulk=2); mirrorB = git(oB, "rev-parse", "main")
use(sA); write(sA, "pages/a.md", "a\n"); write(sB, "pages/b.md", "b\n"); put(["a.md"])
check("pages: two boards never push the same repository (A's mirror has A's page, B's mirror is unmoved and has no page of A's)", holds(oA, "main", "pages/a.md") and git(oB, "rev-parse", "main") == mirrorB and not holds(oB, "main", "pages/a.md") and not holds(sB, "HEAD", "pages/b.md"))
use(sB); put(["b.md"], "Grace Example")
check("pages: the other board then publishes its own page to its own mirror only", holds(oB, "main", "pages/b.md") and not holds(oB, "main", "pages/a.md") and not holds(oA, "main", "pages/b.md"))
# more than three pages are counted in the message
origin, store, other = world(bulk=2); use(store)
for n in "abcd": write(store, f"pages/{n}.md", n + "\n")
put(["a.md", "b.md", "c.md", "d.md"])
check("pages: the message counts the pages when there are more than three", who(store)[2] == "board: 4 pages", who(store))
write(store, "pages/a.md", "a2\n"); put(["a.md", "b.md", "c.md"])
check("pages: the message names only the pages that changed, without the folder", who(store)[2] == "board: page a.md" and names(store) == ["pages/a.md"], (who(store), names(store)))

# the board's own publish, with the switch on as off: exactly as before; it never commits anything under pages/
for on in (False, True):
    def ctx(): return pages_on() if on else contextlib.nullcontext()
    origin, store, other = world(bulk=2); use(store)
    write(store, "board.md", "board, newer\n"); write(store, ITEM, '{"id": 1, "state": "newer"}\n'); real_git = P._git
    P._git = lambda *a, **k: subprocess.CompletedProcess(a, 128, "", "error: open(\"board-data/x\"): Permission denied\nfatal: adding files failed\n") if a[:4] == ("add", "-A", "--", "board-data") else real_git(*a, **k)
    try:
        with ctx(): err = run(P._gitsync, "board: newer", "board.md", "board-data")
    finally: P._git = real_git
    check(f"board publish (pages {'on' if on else 'off'}): git refusing the add of board-data (an unreadable new file in it) raises nothing, and board.md and the tracked item edit are committed and pushed, as on main", sorted(names(store)) == [ITEM, "board.md"] and git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and "Traceback" not in err, (names(store), err))
    origin, store, other = world(bulk=2); use(store); head = git(store, "rev-parse", "HEAD")
    (store / "board-data").rename(store / "board-data.bak"); write(store, "board.md", "board, newer\n")
    with ctx(): err = run(P._gitsync, "board: newer", "board.md", "board-data")
    check(f"board publish (pages {'on' if on else 'off'}): a board-data folder gone from disk is skipped, never committed as a removal", names(store) == ["board.md"] and holds(store, "HEAD", ITEM) and holds(origin, "main", ITEM) and staged(store) == "", (names(store), staged(store)))
    (store / "board-data.bak").rename(store / "board-data")

# the publish itself, through `publish.py`, against a repository with pages on: items as before, never a page, whatever state pages/ is in
PR, po, pother, pcfg = frepo("pages", pages=True); f = flush(pcfg)
check("pages, publish(): a healthy store flushes (control)", f.returncode == 0, (f.returncode, f.stdout[-200:], f.stderr[-400:]))
use(PR)
for n in ("keep", "kept"): write(PR, f"pages/{n}.md", n + "\n")
with pages_on(), as_bot(): P.publish_pages(["keep.md", "kept.md"], "Ada Example")
tracked = git(PR, "ls-tree", "-r", "--name-only", "HEAD", "--", "pages").splitlines()
def no_page_commit(before): return [c for c in git(PR, "rev-list", f"{before}..HEAD").split() if [n for n in names(PR, c) if n.startswith("pages/")]]
write(PR, "board-data/item-9.json", '{"id": 9}\n'); write(PR, "pages/new.md", "nobody named me\n"); write(PR, "pages/.env", "SECRET=1\n"); write(PR, "pages/kept.md.swp", "swap\n"); write(PR, "pages/kept.md", "edited, not named\n")
before = git(PR, "rev-parse", "HEAD"); f = flush(pcfg)
check("pages, publish(): the item goes out and is pushed; no page, stray file or unnamed edit is committed", f.returncode == 0 and holds(po, "main", "board-data/item-9.json") and not no_page_commit(before) and git(po, "rev-parse", "main") == git(PR, "rev-parse", "HEAD") and all(s in porcelain(PR) for s in ("?? pages/new.md", "?? pages/.env", "?? pages/kept.md.swp", "M pages/kept.md")), (f.returncode, f.stderr[-300:], porcelain(PR)))
for state, enter, leave in (("removed", lambda: shutil.move(str(PR / "pages"), str(T / "pages-away")), lambda: shutil.move(str(T / "pages-away"), str(PR / "pages"))),
                            ("emptied", lambda: [p.unlink() for p in (PR / "pages").iterdir() if p.is_file()], lambda: git(PR, "checkout", "-q", "--", "pages")),
                            ("a symbolic link", lambda: (shutil.move(str(PR / "pages"), str(T / "pages-away")), (PR / "pages").symlink_to(T / "elsewhere")), lambda: ((PR / "pages").unlink(), shutil.move(str(T / "pages-away"), str(PR / "pages"))))):
    write(PR, "board-data/item-9.json", '{"id": 9, "state": "' + state + '"}\n'); before = git(PR, "rev-parse", "HEAD")
    enter()
    try: f = flush(pcfg)
    finally: leave()
    check(f"pages, publish(): pages/ {state}: the item goes out, no page is removed or committed, every page still in HEAD and the mirror", f.returncode == 0 and not no_page_commit(before) and git(PR, "ls-tree", "-r", "--name-only", "HEAD", "--", "pages").splitlines() == tracked and holds(po, "main", *tracked), (f.returncode, f.stderr[-300:], no_page_commit(before)))
# publish() takes the same lock (the flock a running put holds), and a git failure in it raises nothing
write(PR, "board-data/item-9.json", '{"id": 9, "state": "locked"}\n'); before = git(PR, "rev-parse", "HEAD")
holder = open(P.LOCK, "a"); fcntl.flock(holder, fcntl.LOCK_EX)
env = {**os.environ, "STACKSHOT_CONFIG": str(pcfg), "PYTHONDONTWRITEBYTECODE": "1"}
proc = subprocess.Popen([sys.executable, str(pathlib.Path(STACK, "stackshot/web/publish.py")), "publish"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=STACK)
def opened_lock(pid):
    try: return any(os.path.realpath(os.path.join(f"/proc/{pid}/fd", fd)) == os.path.realpath(P.LOCK) for fd in os.listdir(f"/proc/{pid}/fd"))
    except OSError: return False
try:
    t0 = time.monotonic()
    while proc.poll() is None and not opened_lock(proc.pid) and time.monotonic() - t0 < 120: time.sleep(0.05)
    reached = opened_lock(proc.pid); time.sleep(2.0)
    waiting = reached and proc.poll() is None and git(PR, "rev-parse", "HEAD") == before
finally:
    fcntl.flock(holder, fcntl.LOCK_UN); holder.close()
    try: out, perr = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired: proc.kill(); out, perr = proc.communicate()
check("pages, publish(): `publish.py publish` waits on the publish flock another holder has, then publishes once it is let go", waiting and proc.returncode == 0 and git(PR, "rev-parse", "HEAD") != before, (reached, waiting, proc.returncode, perr[-300:]))
write(PR, "board-data/item-9.json", '{"id": 9, "state": "index locked"}\n'); before = git(PR, "rev-parse", "HEAD")
(PR / ".git" / "index.lock").write_text("")
try: p = subprocess.run([sys.executable, str(pathlib.Path(STACK, "stackshot/web/publish.py")), "publish"], capture_output=True, text=True, env=env, cwd=STACK, timeout=300)
finally: (PR / ".git" / "index.lock").unlink(missing_ok=True)
check("pages, publish(): a git step that fails (a held index.lock) raises nothing out of publish(), as on main", p.returncode == 0 and "Traceback" not in p.stderr and git(PR, "rev-parse", "HEAD") == before, (p.returncode, p.stderr[-400:]))

# flush with pages off (the default): never looks at pages/; with pages on it does not either (a page is publish_pages()' own)
DR, do, dother, dcfg = frepo("pagesoff")
write(DR, "pages/stray.md", "stray\n"); git(DR, "add", "pages/stray.md")
f = flush(dcfg)
check("pages, flush: with pages off (the example's false) flush commits and pushes board-data only, exit 0", f.returncode == 0 and "committed and pushed" in f.stdout and not holds(do, "main", "pages/stray.md"), (f.returncode, f.stdout[-300:], f.stderr[-300:]))
check("pages, flush: the staged page is left exactly as the session put it", "A  pages/stray.md" in porcelain(DR).splitlines(), porcelain(DR))
FP, fpo, fpother, fpcfg = frepo("pagesflush", pages=True); write(FP, "pages/w.md", "w\n"); f = flush(fpcfg)
check("pages, flush: with pages on, an uncommitted page neither fails the flush nor is committed by it", f.returncode == 0 and not holds(fpo, "main", "pages/w.md") and "?? pages/w.md" in git(FP, "status", "--porcelain", "-uall"), (f.returncode, f.stdout[-200:], f.stderr[-300:]))

# ============================================================= 6. the source itself
src = pathlib.Path(STACK, "stackshot/web/publish.py").read_text(encoding="utf-8")
body = src[src.index("def _gitsync"):src.index("def publish(")]
check("source: _gitsync runs no rebase, stash, checkout or reset", not re.search(r'"(rebase|stash|checkout|reset|switch)"|--autostash', body), body)
check("source: every fast-forward the publisher runs says --no-autostash", src.count('"--ff-only"') == 2 and src.count('"--ff-only", "--no-autostash"') == 2, src.count('"--ff-only"'))
check("source: the only step that moves the live tree is a fast-forward-only merge", re.findall(r'_git\("merge"[^)]*\)', body) == ['_git("merge", "--ff-only", "--no-autostash", "--quiet", target)'] and '"merge-tree", "--write-tree"' in body and '"commit-tree"' in body, re.findall(r'_git\("merge"[^)]*\)', body))
pages_at = src.index("# ---------------------------------------------------------------------------- a brain's pages")
outside = src[:pages_at] + src[src.index("def bump("):]
steps = src[src.index("def _gitsync"):src.index("class NotServerHost")] + src[src.index("def publish("):pages_at] + src[src.index("def bump("):]
check("source: nothing outside the pages section names PAGES_REL beyond its own line, and publish(), _gitsync and the CLI never name pages/ or the switch",
      [l for l in outside.splitlines() if "PAGES_REL" in l] == [l for l in src.splitlines() if l.startswith("PAGES_REL = ")] and not re.search(r'"pages|_pages_on', steps), [l for l in outside.splitlines() if "PAGES_REL" in l])
check("source: no threading.local in the publisher (the server's thread checks refuse one)", "threading.local" not in src)

print(("ok" if not fails else "FAILED") + f": publish_git scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
