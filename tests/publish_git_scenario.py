"""Scenario test for the publisher's git step (`publish._gitsync`): it never rebases, stashes or checks out in the live store clone. Fixture data only:
a bare repository acting as the mirror (origin) and clones acting as the store and another writer, all in scratch folders from tests/_scratch.py;
no network, nothing of the host's touched.

Covers: the store ahead only (pushed, no rebase in the reflog, no note); the store behind only (fast-forwarded, the newer remote file in the working
tree, an uncommitted edit kept, and a refusal where the edit is on a file the mirror changed, naming the file); a store DIVERGED on disjoint files (healed
by a merge made off the live tree: both writers' files present, pushed, the uncommitted item file untouched, the merge's author the store's configured
identity or else its last commit's author; a refusal of the fast-forward onto an uncommitted edit reported); a store diverged on the same files (a real
conflict: nothing in the working tree changes, no stash, HEAD and the refs unchanged, nothing pushed, one line on stderr with the asymmetric counts, repeated
at most hourly per process; `publish.py flush` against it exits non-zero); a poller that reads a tracked, uncommitted item file every 20 ms while a
conflicting publish runs over a few hundred files and finds it never differs from the uncommitted content; a refused push, a non-fast-forward rejection
and a reason line that carries an address, each reported once an hour; a failed fetch, a quiet publish, a file staged by a session, a ref git cannot
compare; and the same conflicting run through the old `rebase --autostash` step (kept below as `old_gitsync`), which the poller catches, so the check
can fail.

    tests/run-suite publish_git        -> exit 0 / 1"""
import contextlib, io, os, pathlib, re, subprocess, sys, threading, time, logging
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
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_NOSYSTEM="1")
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
def commit(repo, msg, **files):
    for name, text in files.items(): write(repo, name, text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg); return git(repo, "rev-parse", "HEAD")
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
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    try: yield
    finally: os.environ.pop("GIT_CONFIG_GLOBAL", None); os.environ.update(saved)
def commit_as(repo, who, msg, **files):
    with no_ident():
        for k in ("AUTHOR", "COMMITTER"): os.environ[f"GIT_{k}_NAME"] = who; os.environ[f"GIT_{k}_EMAIL"] = f"{who.lower().replace(' ', '.')}@x"
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
def disjoint(item_upstream=False, store_cfg=None, last_author=None, ident=False, autostash=False):
    origin, store, other = world(bulk=3); use(store)
    up = {"pages/p.md": "page, written elsewhere\n"}
    if item_upstream: up[ITEM] = '{"id": 1, "state": "elsewhere"}\n'
    O1 = commit(other, "pages from elsewhere", **up); git(other, "push", "-q", "origin", "main")
    if last_author: S1 = commit_as(store, last_author, "store data", **{"board-data/a.json": '{"a": 1}\n'})
    else: S1 = commit(store, "store data", **{"board-data/a.json": '{"a": 1}\n'})
    if store_cfg: git(store, "config", "user.name", store_cfg[0]); git(store, "config", "user.email", store_cfg[1])
    if autostash: git(store, "config", "merge.autoStash", "true")
    write(store, ITEM, DIRTY); mtime = (store / ITEM).stat().st_mtime_ns
    before = state(store)
    if ident:
        with no_ident(): err = run(P._gitsync, "board: x", "board.md")
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
r = disjoint(last_author="Last Author", ident=True)
check("disjoint: with no configured identity, by the author of the store's last commit", git(r["store"], "log", "-1", "--format=%an <%ae> %cn <%ce>") == "Last Author <last.author@x> Last Author <last.author@x>" and git(r["origin"], "rev-parse", "main") == git(r["store"], "rev-parse", "HEAD"), (r["err"], git(r["store"], "log", "-1", "--format=%an <%ae>")))

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
def frepo(name):
    """A data repository the publisher itself runs in (its own config file): (repo, bare mirror, another writer's clone, config path)."""
    fr = T / f"{name}-repo"; fo = T / f"{name}-origin.git"; git(T, "init", "-q", "--bare", "-b", "main", str(fo)); git(T, "clone", "-q", str(fo), str(fr))
    commit(fr, "first", **{"board.md": "board\n", "board-data/README": "data\n"}); git(fr, "branch", "-M", "main"); git(fr, "push", "-q", "-u", "origin", "main")
    fother = T / f"{name}-other"; git(T, "clone", "-q", str(fo), str(fother))
    ft = toml.replace(f'repo = "{tmp}"', f'repo = "{fr}"', 1).replace(f'store = "{tmp}/store"', f'store = "{fr}/board-data"', 1).replace(f'markdown = "{tmp}/board.md"', f'markdown = "{fr}/board.md"', 1)
    assert ft.count(str(fr)) == 3; (T / f"{name}.toml").write_text(ft, encoding="utf-8")
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
NOTE = "pages/note.md"                        # a tracked file outside what the publisher commits, so its edit stays uncommitted through the publish
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

# ============================================================= 6. the source itself
src = pathlib.Path(STACK, "stackshot/web/publish.py").read_text(encoding="utf-8")
body = src[src.index("def _gitsync"):src.index("def publish(")]
check("source: _gitsync runs no rebase, stash, checkout or reset", not re.search(r'"(rebase|stash|checkout|reset|switch)"|--autostash', body), body)
check("source: every fast-forward the publisher runs says --no-autostash", src.count('"--ff-only"') == 2 and src.count('"--ff-only", "--no-autostash"') == 2, src.count('"--ff-only"'))
check("source: the only step that moves the live tree is a fast-forward-only merge", re.findall(r'_git\("merge"[^)]*\)', body) == ['_git("merge", "--ff-only", "--no-autostash", "--quiet", target)'] and '"merge-tree", "--write-tree"' in body and '"commit-tree"' in body, re.findall(r'_git\("merge"[^)]*\)', body))

print(("ok" if not fails else "FAILED") + f": publish_git scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
