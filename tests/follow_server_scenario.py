"""Scenario test for a box that follows the server through a repo move and a history rewrite with no hand step (puller 10), and for the
Machines card that is judged by where the box is. Fixture data only: temporary git repositories acting as the repository (origin),
the server's checkout and the boxes; no network, no real claude, nothing of the host's touched. Every folder comes from tests/_scratch.py.

Covers: the server publishes the repository's canonical address (https, no user, whatever form its origin has; [client] repo_url
overrides it) in the poll's `current`; the address check (one repository in any form of its address is no move; hostile or odd addresses
are no address); a REPO MOVE (origin's URL changes, the old address gone): a clean, idle box takes the new address, fetched from first,
and follows the server, also when it is at the server's commit already; a HISTORY REWRITE (the server's commit is unrelated to the
box's): a clean, idle box saves the rollback branch legacy-<short sha> at its HEAD BEFORE the reset, then `reset --keep` onto the server's
commit, the old commits kept on the branch; both together; a DIRTY box (tracked edit, a merge in progress) and a BUSY box are refused,
nothing changed, and stay red; an address that does not answer leaves the box as it was; a rollback branch that cannot be made refuses
the move before any reset; the card (ui.render.machine_alerts) clears itself when the box reports the server's commit.

    tests/run-suite follow_server        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, subprocess, sys, pathlib, logging, shutil
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="follow-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
for d in ("state", "secrets"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text(f"# hostname\tfleet\tletter\n{socket.gethostname()}\ttestbox\ta\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

GITENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}
def git(cwd, *a, ok=True) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=GITENV)
    assert r.returncode == 0 or not ok, (a, r.stderr)
    return r.stdout.strip()
FILES = {"puller.py": 'VERSION = "10"\n', "client.py": "x = 1\n", "config.py": "y = 1\n", "said.py": "z = 1\n", "README.md": "one\n"}
def commit(repo, msg, **files) -> str:
    for name, text in files.items(): (repo / name).parent.mkdir(parents=True, exist_ok=True); (repo / name).write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg); return git(repo, "rev-parse", "HEAD")
def new_repo(name, **files):
    r = T / name; git(T, "init", "-q", "-b", "main", str(r)); commit(r, "first", **{**FILES, **files}); return r
def clone(src, name):
    git(T, "clone", "-q", str(src), str(T / name)); return T / name
def rewrite(repo, msg, **files) -> str:
    """The repository's history rewritten: main is now an unrelated line (an orphan root), the old commits gone from it."""
    git(repo, "checkout", "-q", "--orphan", "rewritten"); git(repo, "rm", "-q", "-rf", "."); git(repo, "branch", "-q", "-D", "main")
    for name, text in {**FILES, **files}.items(): (repo / name).write_text(text)
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", msg); git(repo, "branch", "-q", "-m", "main"); return git(repo, "rev-parse", "HEAD")

import client, clients as cl, puller, config as _cfg
from ui import render as _render
def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf): out = fn(*a, **k)
    return out, buf.getvalue()
def on(box):
    """Point the puller at `box` with a fresh record (the fixtures start every scenario from nothing)."""
    pathlib.Path(str(_cfg.state("puller-updates.json"))).unlink(missing_ok=True)
    puller.CHECKOUT = str(box); puller._HEAD.update(at=0.0, v=""); puller._STATE = None; puller._SAID.clear(); puller._AHEAD.clear()
    puller._state()["attempts"] = []; puller._state()["tried"] = {}; puller._state()["moved"] = []
head = lambda: (puller._HEAD.update(at=0.0), puller.head())[1]
puller._claude_process = lambda: ""                       # this host may run claude processes; the fixture boxes are idle unless a check says otherwise
CUR = lambda sha, repo="": {"puller": puller.VERSION, "stackshot": sha, "self_update": True, **({"repo": str(repo)} if repo else {})}
legacy = lambda box: git(box, "branch", "--list", "legacy-*", "--format=%(refname:short)").split()
card = lambda box, server: _render.machine_alerts({"updates": puller.attempts(), "stackshot": head()}, server)[1]   # the failures the Machines card would draw
FETCHES = []; _real_git = puller._git
def counting(args, timeout=60, **kw):
    if args[0] == "fetch": FETCHES.append(args[-2:])
    return _real_git(args, timeout, **kw)
puller._git = counting
refs = lambda box: git(box, "for-each-ref", "--format=%(refname) %(objectname)")
BUSY = [{"sessionId": "00000020-0000-4000-8000-000000000000", "name": "work-live"}]

# ============================================================= 1. what the server publishes, and what counts as the same repository
check("canonical_url: an scp-style ssh address → https, no user", cl.canonical_url("git@github.com:acme/widget.git") == "https://github.com/acme/widget.git", cl.canonical_url("git@github.com:acme/widget.git"))
check("canonical_url: ssh:// with a user and a port → https", cl.canonical_url("ssh://git@host.example:2222/o/r.git") == "https://host.example/o/r.git", cl.canonical_url("ssh://git@host.example:2222/o/r.git"))
check("canonical_url: https with a user and a password → https with neither", cl.canonical_url("https://user:secret@github.com/o/r.git") == "https://github.com/o/r.git", cl.canonical_url("https://user:secret@github.com/o/r.git"))
check("canonical_url: a local path and a file:// URL stay as they are; a dash, a space, a helper transport and nothing are no address",
      cl.canonical_url("/srv/r") == "/srv/r" and cl.canonical_url("file:///srv/r") == "file:///srv/r" and [cl.canonical_url(x) for x in ("--upload-pack=x", "a b", "ext::sh -c x", "")] == ["", "", "", ""],
      [cl.canonical_url(x) for x in ("--upload-pack=x", "a b", "ext::sh -c x", "")])
SRV = new_repo("server-checkout"); git(SRV, "remote", "add", "origin", "git@github.com:Acme/Widget.git")
cl.CHECKOUT = str(SRV); cl._REPO.update(at=0.0, v="")
check("repo_url: the server checkout's origin, as https", cl.repo_url() == "https://github.com/Acme/Widget.git", cl.repo_url())
check("current: carries it as `repo`, beside the commit", cl.current("box-far").get("repo") == "https://github.com/Acme/Widget.git" and set(cl.current("box-far")) == {"puller", "stackshot", "self_update", "repo"}, cl.current("box-far"))
_cfg.CFG["client"]["repo_url"] = "git@git.example.org:team/stackshot.git"
check("repo_url: [client] repo_url wins over the checkout's origin", cl.repo_url() == "https://git.example.org/team/stackshot.git", cl.repo_url())
_cfg.CFG["client"]["repo_url"] = ""
git(SRV, "remote", "remove", "origin"); cl._REPO.update(at=0.0, v="")
check("current: a checkout with no origin publishes no `repo` (the key is absent, nothing to follow)", "repo" not in cl.current("box-far"), cl.current("box-far"))

same = [("https://github.com/Acme/Widget.git", "git@github.com:acme/widget.git"), ("https://github.com/o/r", "ssh://git@github.com:22/o/r.git"), ("https://user@github.com/o/r/", "https://github.com/o/r.git")]
check("repo_id: one repository in any form of its address is the same (case, .git, user, port, scheme)", all(puller._repo_id(a) == puller._repo_id(b) for a, b in same), [(puller._repo_id(a), puller._repo_id(b)) for a, b in same])
check("repo_id: another owner, another host or another repository is another", len({puller._repo_id(x) for x in ("https://github.com/o/r", "https://github.com/p/r", "https://gitlab.com/o/r", "https://github.com/o/s")}) == 4)
check("repo_id: a local path is its normalised absolute path", puller._repo_id(str(T / "x/../y")) == puller._repo_id(str(T / "y")) != puller._repo_id(str(T / "z")))
check("address_ok: the shapes git is given", all(puller._address_ok(x) for x in ("https://github.com/o/r.git", "ssh://git@host/o/r", "git@github.com:o/r.git", "/srv/r", "file:///srv/r", "C:\\repos\\r")))
check("address_ok: never a dash, a space, a newline, a helper transport or nothing", not any(puller._address_ok(x) for x in ("--upload-pack=x", "-x", "a b", "https://h/r\nx", "ext::sh -c x", "fd::3", "", " https://h/r")))

# ============================================================= 2. a repo move: the old address is gone, the box takes the new one
OLD = new_repo("old-origin"); BOX1 = clone(OLD, "box1")
NEW = clone(OLD, "new-origin")                                # the repository moved: same history, a new address
N1 = commit(NEW, "after the move", **{"README.md": "two\n"})
shutil.rmtree(OLD)                                            # the old address answers nothing
on(BOX1); A0 = head()
rc, out = quiet(puller.keep_current, CUR(N1, NEW), [])
check("repo move: a clean, idle box behind the server takes the new address, fetches from it and follows the server (then reloads)",
      rc == puller.RELOAD and head() == N1 and git(BOX1, "remote", "get-url", "origin") == str(NEW) and puller.attempts()[-1]["ok"] is True and puller.attempts()[-1]["reason"] == ""
      and (BOX1 / "README.md").read_text() == "two\n" and legacy(BOX1) == [], (rc, out, puller.attempts()))
check("repo move: the card is clear (the box is at the server's commit)", card(BOX1, N1) == [], card(BOX1, N1))
check("repo move: origin's remote-tracking refs follow the new address, and no private fetch ref is left behind", git(BOX1, "rev-parse", "refs/remotes/origin/main") == N1 and "stackshot-incoming" not in refs(BOX1), refs(BOX1))

# at the server's commit already, only the address is wrong: taken with no attempt and no reload
OLD2 = new_repo("old-origin2"); BOX2 = clone(OLD2, "box2"); NEW2 = clone(OLD2, "new-origin2"); shutil.rmtree(OLD2)
on(BOX2); S2 = head()
rc, out = quiet(puller.keep_current, CUR(S2, NEW2), [])
check("repo move: a box at the server's commit takes the new address all the same, with no attempt recorded and no reload", rc is None and git(BOX2, "remote", "get-url", "origin") == str(NEW2) and puller.attempts() == [] and "ok" in out, (rc, out))
rc, out = quiet(puller.keep_current, CUR(S2, NEW2), [])
check("repo move: …and the next poll says nothing", rc is None and out == "", out)

# the new address does not answer: the box is as it was
OLD3 = new_repo("old-origin3"); BOX3 = clone(OLD3, "box3"); on(BOX3); S3 = head()
GONE = str(T / "nowhere/repo")
rc, out = quiet(puller.keep_current, CUR(S3, GONE), [])
check("repo move: a new address that does not answer leaves the origin as it was, and the failure is logged", git(BOX3, "remote", "get-url", "origin") == str(OLD3) and "FAILED" in out and "repo address " + GONE in out, (rc, out))
rc2, out2 = quiet(puller.keep_current, CUR(S3, GONE), [])
check("repo move: …said once", out2 == "", out2)
check("backoff: a failed address is fetched once, not on every poll (the second poll makes no network call)", [f for f in FETCHES if f[0] == GONE or GONE in f[0]] == [[GONE, f"+refs/heads/*:{puller._INCOMING}/*"]], FETCHES)
tr = puller._state()["tried"]["repo address"]
check("backoff: it is kept in the box's try record, keyed on the address (n = 1)", tr["to"] == GONE and tr["n"] == 1 and tr["why"].startswith("repo address " + GONE), tr)
for _ in range(3): quiet(puller.keep_current, CUR(S3, GONE), [])
check("backoff: …still one fetch after more polls", len([f for f in FETCHES if GONE in f[0]]) == 1, FETCHES)
puller._state()["tried"]["repo address"]["at"] -= 3601
quiet(puller.keep_current, CUR(S3, GONE), []); quiet(puller.keep_current, CUR(S3, GONE), [])
check("backoff: after the hour one more try, n = 2, then it waits 4 h", len([f for f in FETCHES if GONE in f[0]]) == 2 and puller._state()["tried"]["repo address"]["n"] == 2, (FETCHES, puller._state()["tried"]))
puller._state()["tried"]["repo address"]["at"] -= 3601
quiet(puller.keep_current, CUR(S3, GONE), [])
check("backoff: …4 h are not over after 1 h more", len([f for f in FETCHES if GONE in f[0]]) == 2)
puller._state()["tried"]["repo address"]["at"] -= 4 * 3600
quiet(puller.keep_current, CUR(S3, GONE), [])
check("backoff: after 4 h more, a third try (then daily)", len([f for f in FETCHES if GONE in f[0]]) == 3 and puller._state()["tried"]["repo address"]["n"] == 3, puller._state()["tried"])
N3 = commit(OLD3, "more", **{"README.md": "more\n"})
n_before = len([f for f in FETCHES if GONE in f[0]])
rc, out = quiet(puller.keep_current, CUR(N3, GONE), [])
check("backoff: the update of a box behind the server does not fetch the failed address again either; its attempt says why", len([f for f in FETCHES if GONE in f[0]]) == n_before, FETCHES)
puller._state()["tried"].pop("stackshot checkout", None)
rc, out = quiet(puller.keep_current, CUR(N3, GONE), [])
check("repo move: a box behind the server whose new address does not answer fails the attempt with that reason and stays on its old address (red until it matches)",
      rc is None and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"].startswith("repo address " + GONE + ": git fetch: ") and git(BOX3, "remote", "get-url", "origin") == str(OLD3)
      and head() == S3 and card(BOX3, N3) != [], (rc, out, puller.attempts()))

# the new address answers but does not hold the server's commit: nothing of the box changes
OLD3b = new_repo("old-origin3b"); BOX3b = clone(OLD3b, "box3b"); on(BOX3b); S3b = head()
OTHER = new_repo("other-origin", **{"README.md": "an unrelated repository\n"}); refs_before = refs(BOX3b)
rc, out = quiet(puller.keep_current, CUR(S3b, OTHER), [])
check("holds the commit: an address that answers but lacks the server's commit is not taken: origin, its remote-tracking refs and the private namespace are as they were",
      git(BOX3b, "remote", "get-url", "origin") == str(OLD3b) and refs(BOX3b) == refs_before and "stackshot-incoming" not in refs(BOX3b) and "does not hold the server's commit " + S3b[:12] in out, (rc, out, refs(BOX3b)))
check("holds the commit: …and the failure waits out its backoff like any other", puller._state()["tried"]["repo address"]["n"] == 1)

# a ref left in the private namespace by a run that was killed must not make an address look as if it held the commit
OLD3c = new_repo("old-origin3c"); BOX3c = clone(OLD3c, "box3c"); on(BOX3c); S3c = head()
OTHER2 = new_repo("other-origin2", **{"README.md": "another unrelated repository\n"})
git(BOX3c, "update-ref", puller._INCOMING + "/left-by-a-killed-run", S3c)
rc, out = quiet(puller.keep_current, CUR(S3c, OTHER2), [])
check("stale ref: a leftover ref at the server's commit plus an address of unrelated history is refused, and the leftover is gone",
      git(BOX3c, "remote", "get-url", "origin") == str(OLD3c) and "does not hold the server's commit " + S3c[:12] in out and "stackshot-incoming" not in refs(BOX3c), (rc, out, refs(BOX3c)))

# without a commit to check, an address that answers with no branch at all is no address to move to
OLD3d = new_repo("old-origin3d"); BOX3d = clone(OLD3d, "box3d"); on(BOX3d)
EMPTY = T / "empty-origin"; git(T, "init", "-q", "--bare", str(EMPTY))
ch, why = puller._take_repo(str(EMPTY), "")
check("no branches: an empty repository is not taken when the server's commit is unknown: origin is as it was, the reason says so",
      ch is False and why == f"repo address {EMPTY}: it has no branches" and git(BOX3d, "remote", "get-url", "origin") == str(OLD3d) and "stackshot-incoming" not in refs(BOX3d), (ch, why))
puller._state()["tried"].pop("repo address", None)
NONEMPTY = new_repo("nonempty-origin")
ch, why = puller._take_repo(str(NONEMPTY), "")
check("no branches: …while a repository with a branch is taken without a commit to check", ch is True and git(BOX3d, "remote", "get-url", "origin") == str(NONEMPTY) and "stackshot-incoming" not in refs(BOX3d), (ch, why))

# the same repository reached another way is no move
OLD4 = new_repo("old-origin4"); BOX4 = clone(OLD4, "box4"); on(BOX4); S4 = head()
git(BOX4, "remote", "set-url", "origin", "git@github.com:Acme/Widget.git")
rc, out = quiet(puller.keep_current, CUR(S4, "https://github.com/acme/widget.git"), [])
check("repo move: the same repository in its https form is no move: the ssh address is left, nothing fetched or said", rc is None and "repo address" not in out and git(BOX4, "remote", "get-url", "origin") == "git@github.com:Acme/Widget.git", (rc, out))

# ============================================================= 3. a history rewrite: the server's commit is unrelated to the box's
RW = new_repo("rw-origin", **{"README.md": "old line\n"}); BOX5 = clone(RW, "box5"); on(BOX5); OLDHEAD = head()
(BOX5 / "local.txt").write_text("box's own work\n"); git(BOX5, "add", "-A"); git(BOX5, "commit", "-q", "-m", "a commit of the box's own"); OWN = head()
W1 = rewrite(RW, "history rewritten", **{"README.md": "new line\n"})
seen = []; _g = puller._git
def watch(args, timeout=60, **kw):
    if args[:2] == ["reset", "--keep"]: seen.append(git(BOX5, "branch", "--list", "legacy-*", "--format=%(refname:short) %(objectname)"))
    return _g(args, timeout, **kw)
puller._git = watch
rc, out = quiet(puller.keep_current, CUR(W1, RW), [])
puller._git = _g
check("rewrite: a clean, idle box whose history is not the server's is moved onto the server's commit, with a reload, no hand step", rc == puller.RELOAD and head() == W1 and (BOX5 / "README.md").read_text() == "new line\n", (rc, out, head()))
check("rewrite: the rollback branch legacy-<short sha> is at the old HEAD (the box's own commit), and was there BEFORE the reset", legacy(BOX5) == [f"legacy-{OWN[:12]}"] and git(BOX5, "rev-parse", f"legacy-{OWN[:12]}") == OWN
      and seen == [f"legacy-{OWN[:12]} {OWN}"], (legacy(BOX5), seen))
check("rewrite: the old commits are all still reachable from it (nothing lost)", git(BOX5, "rev-list", "--count", f"legacy-{OWN[:12]}") == "2" and git(BOX5, "show", f"legacy-{OWN[:12]}:local.txt") == "box's own work", git(BOX5, "rev-list", "--count", f"legacy-{OWN[:12]}"))
at = puller.attempts()[-1]
check("rewrite: the attempt says so (ok, recovered, the branch named) and the recovery is on the box's record", at["ok"] is True and at["reason"] == f"recovered: left {OWN[:12]}, which is not in origin/main (saved as legacy-{OWN[:12]})"
      and puller._state()["recovered"][-1]["from"] == OWN and puller._state()["recovered"][-1]["to"] == W1, (at, puller._state()))
check("rewrite: the card is clear", card(BOX5, W1) == [], card(BOX5, W1))
check("rewrite: nothing was hard-reset and the tree is clean", git(BOX5, "status", "--porcelain", "--untracked-files=no") == "" and git(BOX5, "rev-parse", "HEAD") == W1)
rc, out = quiet(puller.keep_current, CUR(W1, RW), [])
check("rewrite: the next poll does nothing", rc is None and out == "" and len(legacy(BOX5)) == 1, (rc, out))

# both at once: the repository moved AND its history was rewritten (a new repository with a new line)
OLD6 = new_repo("old-origin6"); BOX6 = clone(OLD6, "box6"); on(BOX6); H6 = head()
NEW6 = new_repo("new-origin6", **{"README.md": "fresh start\n"}); W6 = git(NEW6, "rev-parse", "HEAD"); shutil.rmtree(OLD6)
rc, out = quiet(puller.keep_current, CUR(W6, NEW6), [])
check("move and rewrite together: the box takes the new address, saves legacy-<sha> at its old HEAD and follows the server's commit, in one poll",
      rc == puller.RELOAD and head() == W6 and git(BOX6, "remote", "get-url", "origin") == str(NEW6) and legacy(BOX6) == [f"legacy-{H6[:12]}"] and git(BOX6, "rev-parse", f"legacy-{H6[:12]}") == H6
      and card(BOX6, W6) == [], (rc, out, puller.attempts()))

# ============================================================= 4. refused, and red until the box is where it should be
RW7 = new_repo("rw-origin7"); BOX7 = clone(RW7, "box7"); on(BOX7); H7 = head()
W7 = rewrite(RW7, "history rewritten")
(BOX7 / "README.md").write_text("edited on the box\n")
rc, out = quiet(puller.keep_current, CUR(W7, RW7), [])
at = puller.attempts()[-1]
check("dirty: a box with an edited tracked file is refused: HEAD, the edit and the branches stay, nothing is created", rc is None and head() == H7 and (BOX7 / "README.md").read_text() == "edited on the box\n" and legacy(BOX7) == []
      and at["ok"] is False and at["reason"] == "local changes in the checkout", (rc, out, at))
check("dirty: …and the card is red (the box is not at the server's commit and its last attempt failed)", [u["what"] for u in card(BOX7, W7)] == ["stackshot checkout"], card(BOX7, W7))
git(BOX7, "checkout", "--", "README.md"); puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(W7, RW7), [])
check("dirty: once the edit is gone the same box moves by itself, and the card is clear while the failed attempt is still on record", rc == puller.RELOAD and head() == W7 and legacy(BOX7) == [f"legacy-{H7[:12]}"] and card(BOX7, W7) == [], (rc, out))

RW8 = new_repo("rw-origin8"); BOX8 = clone(RW8, "box8"); on(BOX8); H8 = head()
git(BOX8, "bisect", "start")                                  # a bisect under way: the tree is clean, the checkout is not free
W8 = rewrite(RW8, "history rewritten")
rc, out = quiet(puller.keep_current, CUR(W8, RW8), [])
check("busy checkout: an operation in progress (a bisect here; a merge, rebase, cherry-pick or revert the same) is refused, though the tree is clean: nothing moved, no branch",
      rc is None and puller.attempts()[-1]["ok"] is False and puller.attempts()[-1]["reason"] == "a git operation is in progress in the checkout (BISECT_LOG)" and head() == H8 and legacy(BOX8) == [], (rc, out, puller.attempts()))
git(BOX8, "bisect", "reset")

RW9 = new_repo("rw-origin9"); BOX9 = clone(RW9, "box9"); on(BOX9); H9 = head()
OLD9 = new_repo("old-origin9"); git(BOX9, "remote", "set-url", "origin", str(OLD9)); W9 = rewrite(RW9, "history rewritten")
rc, out = quiet(puller.keep_current, CUR(W9, RW9), BUSY)
check("busy: a box with a live session is not touched: no address change, no branch, no move, said once", rc is None and head() == H9 and git(BOX9, "remote", "get-url", "origin") == str(OLD9) and legacy(BOX9) == []
      and puller.attempts() == [] and out.count("waiting, 1 live session(s): work-live") == 2, (rc, out))      # (the address and the update each wait, once)
puller._claude_process = lambda: "a claude process is running"
rc, out = quiet(puller.keep_current, CUR(W9, RW9), [])
puller._claude_process = lambda: ""
check("busy: …nor with a claude process running", rc is None and head() == H9 and git(BOX9, "remote", "get-url", "origin") == str(OLD9) and legacy(BOX9) == [], (rc, out))
(BOX9 / "README.md").write_text("edited on the box\n")
rc, out = quiet(puller.keep_current, CUR(W9, RW9), [])
check("dirty and moved repo: the address stays too (a dirty box is not reconfigured), the update is refused", git(BOX9, "remote", "get-url", "origin") == str(OLD9) and puller.attempts()[-1]["reason"] == "local changes in the checkout" and head() == H9, (rc, out, puller.attempts()))
git(BOX9, "checkout", "--", "README.md")

# --dry-run says what it would do and does none of it
rc, out = quiet(puller.keep_current, CUR(W9, RW9), [], True)
check("dry-run: names the address it would take, changes nothing", "would take the repo address " + str(RW9) in out and git(BOX9, "remote", "get-url", "origin") == str(OLD9) and head() == H9 and legacy(BOX9) == [], out)

# ============================================================= 5. never destructive: no branch, no reset
RW10 = new_repo("rw-origin10"); BOX10 = clone(RW10, "box10"); on(BOX10); H10 = head(); W10 = rewrite(RW10, "history rewritten")
calls = []
def no_branch(args, timeout=60, **kw):
    calls.append(args[:2])
    if args[0] == "branch": return 128, "", "fatal: cannot lock ref"
    return _g(args, timeout, **kw)
puller._git = no_branch
rc, out = quiet(puller.keep_current, CUR(W10, RW10), [])
puller._git = _g
check("rollback branch: one that cannot be made refuses the move before any reset", rc is None and head() == H10 and ["reset", "--keep"] not in calls and puller.attempts()[-1]["ok"] is False
      and puller.attempts()[-1]["reason"].startswith("could not save the rollback branch legacy-" + H10[:12]), (rc, out, puller.attempts()[-1]))
def lies(args, timeout=60, **kw):
    if args[0] == "branch": return 0, "", ""                     # claims success and made nothing
    return _g(args, timeout, **kw)
puller._git = lies; puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(W10, RW10), [])
puller._git = _g
check("rollback branch: one that does not read back refuses the move too", rc is None and head() == H10 and "does not read back" in puller.attempts()[-1]["reason"], (rc, out, puller.attempts()[-1]))
puller._state()["tried"].clear(); (BOX10 / "clash.txt").write_text("mine, untracked\n"); commit(RW10, "main moves", **{"clash.txt": "from main\n"}); W10b = git(RW10, "rev-parse", "HEAD")
rc, out = quiet(puller.keep_current, CUR(W10b, RW10), [])
check("untracked file in the way: git's own refusal (reset --keep) stops the move, the file stays, and the branch that was made stays too (it only holds the old commit)",
      rc is None and head() == H10 and (BOX10 / "clash.txt").read_text() == "mine, untracked\n" and puller.attempts()[-1]["reason"].startswith("git reset --keep: ") and git(BOX10, "rev-parse", f"legacy-{H10[:12]}") == H10, (rc, out, puller.attempts()[-1]))
# an ignored untracked file that the target tracks: git's reset --keep / fast-forward would replace it without a word, so the move is refused
RW12 = new_repo("rw-origin12", **{".gitignore": "secret.cfg\n"}); BOX12 = clone(RW12, "box12"); on(BOX12); H12 = head()
(BOX12 / "secret.cfg").write_text("the box's own, ignored\n")
W12 = rewrite(RW12, "history rewritten, secret.cfg tracked now", **{"secret.cfg": "from main\n"})
rc, out = quiet(puller.keep_current, CUR(W12, RW12), [])
check("ignored file: a history rewrite that tracks a file the box keeps ignored is refused before anything is changed (no rollback branch, HEAD and the file stay), red",
      rc is None and head() == H12 and (BOX12 / "secret.cfg").read_text() == "the box's own, ignored\n" and legacy(BOX12) == [] and puller.attempts()[-1]["ok"] is False
      and puller.attempts()[-1]["reason"] == "untracked ignored file(s) in the way: secret.cfg" and card(BOX12, W12) != [], (rc, out, puller.attempts()[-1]))
(BOX12 / "secret.cfg").unlink(); puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(W12, RW12), [])
check("ignored file: once the file is gone the same box moves (rollback branch first)", rc == puller.RELOAD and head() == W12 and legacy(BOX12) == [f"legacy-{H12[:12]}"], (rc, out))
# the fast-forward path too
RW13 = new_repo("rw-origin13", **{".gitignore": "secret.cfg\n"}); BOX13 = clone(RW13, "box13"); on(BOX13); H13 = head()
(RW13 / "secret.cfg").write_text("from main\n"); git(RW13, "add", "-f", "secret.cfg"); git(RW13, "commit", "-q", "-m", "track secret.cfg"); F13 = git(RW13, "rev-parse", "HEAD")
(BOX13 / "secret.cfg").write_text("the box's own, ignored\n")
rc, out = quiet(puller.keep_current, CUR(F13, RW13), [])
check("ignored file: the same on a plain fast-forward: refused, the file and HEAD stay", rc is None and head() == H13 and (BOX13 / "secret.cfg").read_text() == "the box's own, ignored\n"
      and puller.attempts()[-1]["reason"].startswith("untracked ignored file(s) in the way: secret.cfg"), (rc, out, puller.attempts()[-1]))
(BOX13 / "keep.log").write_text("not in the way\n"); (BOX13 / "secret.cfg").unlink(); puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(F13, RW13), [])
check("ignored file: an ignored file the target does not track is no obstacle", rc == puller.RELOAD and head() == F13, (rc, out))

# a path with a tab, quotes or a newline is one name for the guard
ODD = 'odd\tname "q"\nx.cfg'
RW14 = new_repo("rw-origin14", **{".gitignore": "*.cfg\n"}); BOX14 = clone(RW14, "box14"); on(BOX14); H14 = head()
(RW14 / ODD).write_text("from main\n"); git(RW14, "add", "-f", "--", ODD); git(RW14, "commit", "-q", "-m", "track an oddly named file"); F14 = git(RW14, "rev-parse", "HEAD")
(BOX14 / ODD).write_text("the box's own, ignored\n")
rc, out = quiet(puller.keep_current, CUR(F14, RW14), [])
check("ignored file: a name with a tab, quotes and a newline is still guarded (NUL-separated lists)", rc is None and head() == H14 and (BOX14 / ODD).read_text() == "the box's own, ignored\n"
      and puller.attempts()[-1]["reason"].startswith("untracked ignored file(s) in the way: "), (rc, out, puller.attempts()[-1]))

src = pathlib.Path(STACK, "puller.py").read_text(encoding="utf-8")
check("never --hard: the puller's source runs no `reset --hard`", not re.search(r"""\[\s*["']reset["']\s*,\s*["']--hard""", src))

# ============================================================= 6. an ordinary lag and a box ahead on main are as before
LG = new_repo("lag-origin"); BOX11 = clone(LG, "box11"); on(BOX11); L1 = commit(LG, "main moves", **{"README.md": "lag\n"})
rc, out = quiet(puller.keep_current, CUR(L1, LG), [])
check("ordinary lag: fast-forwarded, no rollback branch, the address untouched", rc == puller.RELOAD and head() == L1 and legacy(BOX11) == [] and git(BOX11, "remote", "get-url", "origin") == str(LG), (rc, out))
git(LG, "checkout", "-q", "-b", "keep"); AH = commit(LG, "ahead", **{"README.md": "ahead\n"}); git(LG, "checkout", "-q", "main"); git(LG, "merge", "-q", "--ff-only", "keep")
git(BOX11, "fetch", "-q", "origin"); git(BOX11, "reset", "-q", "--hard", AH); head(); puller._state()["tried"].clear()
rc, out = quiet(puller.keep_current, CUR(L1, LG), [])
check("ahead on main: a box ahead of the server's commit (its HEAD is in origin/main) is left alone, said once", rc is None and head() == AH and legacy(BOX11) == [] and "nothing to do, this checkout is ahead" in out, (rc, out))

print(("ok" if not fails else "FAILED") + f": follow_server scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
