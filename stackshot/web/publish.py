"""publish.py — the stackshot publisher.

publish()   refresh the version tracker + the project-page registry, render board.md from the
            store, commit board-data/ + board.md + projects.json when anything changed, fetch, then push, fast-forward or (diverged on disjoint files) merge off the live tree; never a rebase. One flock; safe to call often.
            It never commits anything under pages/, whatever [publish] pages says.
publish_pages(paths, author, email)  [publish] pages on only: commit the page files the caller names (relative to pages/) as one commit, the named person or agent
            as git author, the board's own identity as committer, then push. True: committed; False: those files are as committed already; CommitFailed: not
            committed, with why (the switch off, a path or an author refused before anything is staged, the clone midway, a file not named that would go with
            them or that a session staged and would lose, git refusing), the store clone's index as it was (the commit is built in an index of its own).
pages_lock()  the publish lock, for a caller to hold across a page's write and its publish_pages(), which nests inside it.
bump()      refresh the latest-version lookups (npm, gbrain releases), then publish; installed versions come from the
            fleet state the fleet tool writes before calling it. `--host` is accepted and ignored (the split).
brief()     the one-line brief + top items (session-start banner).
flush       (CLI) publish, then verify board-data is committed and pushed — the item reboot hook's stop step.

CLI:  publish.py publish | flush | bump [--host <fleet-name>] | brief | render [full|brief]
publish, bump and flush, as commands, run on the server host only: the board is rendered from this box's own copy of the store and its own state, so on a box whose
config names another server ([release] deploy_ssh, or [server] box = false) they are refused with one line that says where to run them, before anything is fetched or
written (publish() raises NotServerHost; the CLI exits 1). The same holds for a script or a pass run by hand that reaches publish(). A serving process (the server and
`stackshot minute`, which say so with serving()) publishes without asking. brief and render only read, and run anywhere.
The server imports this and calls publish() after every write (debounced), on its timer and when the fleet state changes.
_publish()  the debounced call the server makes after a write (with `_publish_now`, `_publish_if_idle`, the timer `_PUB_TIMER` and its lock); a burst of writes publishes once, a few seconds after the first.
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import contextlib
import fcntl
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from stackshot.core import agentbox as _agentbox  # noqa: E402
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.projects import pages as _pages  # noqa: E402
from stackshot.projects import project_registry as _preg  # noqa: E402  — roles.json and projects.json follow a publish
from stackshot.web.board_home import _board_home_drop  # noqa: E402  — a publish drops the board's kept home
from stackshot.core import readonly as _ro  # noqa: E402  — a warm standby copy renders in memory only (_ro_board in web/routes/board_pages.py), never here
from stackshot.fleet import versions as _ver  # noqa: E402
from stackshot.web.render import render, render_all  # noqa: E402

REPO = _cfg.path("paths", "repo")
DATA = _cfg.path("paths", "store")
OUT = _cfg.path("paths", "markdown")
DATA_REL = str(DATA.relative_to(REPO))
OUT_REL = str(OUT.relative_to(REPO))
PAGES_REL = "pages"                      # a brain's pages: markdown files it writes here and never commits (publish_pages() does, for the files it is given)
LOCK = _cfg.state("publish.lock")        # one publish at a time
# [paths] is restart-only (config.RESTART_ONLY); [publish] git and pages are read at use, so a reload is live at once.


def _git_on() -> bool:      # false: render only, never fetch, commit or push (a staging instance)
    return bool(_cfg.get("publish", "git", default=True))


def _pages_on() -> bool:    # only a TOML true turns it on (a string "false" is not true); off, the default, publish_pages() commits nothing
    return _cfg.get("publish", "pages", default=False) is True


def _git(*args: str, check: bool = False, env: dict[str, str] | None = None, new_session: bool = False) -> subprocess.CompletedProcess:
    """git in the store clone (`env`: the whole environment of that one call, else this process's). Its output is read as UTF-8, and a byte that is not (a
    hook's message, a remote's refusal) is read as U+FFFD, never raised on. `new_session`: git runs in a process group of its own, so a terminal's Ctrl-C
    (sent to this process's group) does not reach it or its hooks."""
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, encoding="utf-8", errors="replace", check=check, env=env, start_new_session=new_session)


_NOTED: dict[str, float] = {}      # kind of note -> when it was last printed (time.monotonic)
_NOTE_EVERY = 3600.0               # a note repeats at most hourly per process: the publish runs every few seconds after a write


def _note(kind: str, text: str) -> None:
    now = time.monotonic()
    if kind in _NOTED and now - _NOTED[kind] < _NOTE_EVERY:
        return
    _NOTED[kind] = now
    print(text, file=sys.stderr)


_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+|\S+@\S+:\S+")      # an address, whatever its scheme (an scp-style one included)


def _why(r: subprocess.CompletedProcess) -> str:
    """Why a push was refused, in the mirror's own words (its first `remote:` line) or the ref's rejection; a line that carries an address is skipped."""
    lines = [l.strip() for l in r.stderr.splitlines()]
    for pick in (lambda l: l.startswith("remote:"), lambda l: "rejected]" in l):
        for l in lines:
            if pick(l) and not _URL.search(l) and l.removeprefix("remote:").strip():
                return l
    return "no reason given"


def _refused(r: subprocess.CompletedProcess) -> str:
    """The line of a refused `git merge` that says why (a `fatal:` or `error:` line, else the first), with the file it names when git's next line does (a tab-indented path under "would be overwritten")."""
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    if not lines:
        return "no reason given"
    at = next((i for i, l in enumerate(lines) if l.startswith(("fatal:", "error:"))), 0)
    files = [l.strip() for l in lines[at + 1:] if l.startswith(("\t", "    "))]
    return lines[at].strip() + (f" ({files[0]})" if files else "")


def _identity() -> dict[str, str]:
    """The environment a commit made off the live tree needs: the store clone's own configured identity; where it has none, this process's committer
    (GIT_COMMITTER_NAME, GIT_COMMITTER_EMAIL: the board's own); where that is unset too, the committer of the store's last commit. Never an author: the last
    commit may be a page whose author is a person (publish_pages), and the board's merge is not theirs."""
    env = {}
    for key, cfg, fmt in (("NAME", "name", "cn"), ("EMAIL", "email", "ce")):
        v = (_git("config", f"user.{cfg}").stdout.strip() or os.environ.get(f"GIT_COMMITTER_{key}", "").strip()
             or _git("log", "-1", f"--format=%{fmt}").stdout.strip())
        if v:
            env[f"GIT_AUTHOR_{key}"] = env[f"GIT_COMMITTER_{key}"] = v
    return env


_MID = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD")      # what git leaves in its directory while an operation of a session is unfinished


def _midway() -> str:
    """What the store clone is in the middle of, as a phrase, or "" when the publisher's git step may run: a session's rebase, merge, cherry-pick or revert that is
    not finished, a detached HEAD (a checkout of a commit, a rebase stopped at `edit`) or a branch with no commit yet. A commit, a merge or a push made then would land on that
    HEAD, not on the branch, and be lost or stranded. The git directory is asked for, not assumed: in a linked worktree `.git` is a file."""
    g = _git("rev-parse", "--git-dir")
    if g.returncode != 0 or not g.stdout.strip():
        return ""                                                                        # not a repository at all: the git step fails on its own, as it always did
    here = REPO / g.stdout.strip()
    found = next((m for m in _MID if (here / m).exists()), "")
    if found:
        return "in the middle of a " + {"rebase-merge": "rebase", "rebase-apply": "rebase", "MERGE_HEAD": "merge", "CHERRY_PICK_HEAD": "cherry-pick", "REVERT_HEAD": "revert"}[found]
    if _git("symbolic-ref", "-q", "HEAD").returncode != 0:
        return "on a detached HEAD"
    if _git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return "on a branch with no commit yet"
    return ""


def _gitsync(msg: str, *paths: str, committed: bool = False) -> None:
    """Commit the given paths and push. `--only` with the pathspecs: the server shares this checkout with every session on
    the host, and a plain commit swept in whatever a session had staged (a deletion went out under a board message).
    `committed`: a commit was made just before this call (publish_pages' own, which then calls this with no path), so the push step runs.
    While a session has the clone midway through something (`_midway`) the whole step is skipped, with one note an hour, and the files stay as they are."""
    if (why := _midway()):
        _note("midway", f"publish: the store clone is {why}; the git step (commit, merge, push) waits until it is finished")
        return
    have = [p for p in paths if (REPO / p).exists()]
    for p in have:
        _git("add", "-A", "--", p)
    if have and _git("diff", "--cached", "--quiet", "--", *have).returncode != 0:
        _git("commit", "--quiet", "--only", "-m", msg, "--", *have); committed = True
    if not committed and _git("rev-list", "--count", "@{u}..HEAD").stdout.strip() in ("", "0"):
        return                                                   # a quiet publish: nothing to push, no fetch or rebase either
    if _git("fetch", "--quiet", "origin", "main").returncode != 0:
        return
    # Nothing here rebases, stashes or checks out: a rebase of a diverged clone rewrote the live working tree for seconds on every attempt and a write made
    # then was lost. Where origin stands decides the step. Other writers (an editor on a laptop, a session on the host) push pages to the same repository, so
    # the clone can diverge from origin on DISJOINT files, and that heals by a merge made off the live tree (`merge-tree` and `commit-tree` touch no file; the
    # fast-forward to the merge changes only files the origin side changed, and git refuses it where one has an uncommitted edit). A real conflict is left
    # alone and noted once an hour: it needs a manual fix.
    def push() -> None:
        r = _git("push", "--quiet", "origin", "main")
        if r.returncode != 0:
            _note("push", f"publish: git push was refused: {_why(r)}")
    def forward(target: str, was: str = "") -> bool:
        r = _git("merge", "--ff-only", "--no-autostash", "--quiet", target)
        if r.returncode != 0 and not (was and _git("rev-parse", "HEAD").stdout.strip() != was):    # a session that committed meanwhile is no failure: the next cycle makes the merge again
            _note("merge", f"publish: fast-forward to the mirror failed: {_refused(r)}")
        return r.returncode == 0
    # Both refs are read once, here: every step below works on these two commits, never on the names again. A name read twice can have moved between the reads
    # (a session commits in this checkout, a fetch moves origin/main), and a merge commit whose tree came from one pair of commits and whose parents are another
    # pair is accepted by the fast-forward and drops a file.
    heads = [_git("rev-parse", "--verify", ref) for ref in ("HEAD", "origin/main")]
    if any(h.returncode != 0 or not h.stdout.strip() for h in heads):
        _note("refs", f"publish: could not read the store's or the mirror's head (git exit {max(h.returncode for h in heads)}); nothing pushed")
        return
    mine, theirs = (h.stdout.strip() for h in heads)
    up = _git("merge-base", "--is-ancestor", theirs, mine).returncode                    # 0: origin is behind or equal; 1: not; more: git failed
    if up == 0:                                                                          # push what origin lacks
        if _git("rev-list", "--count", f"{theirs}..{mine}").stdout.strip() not in ("", "0"):
            push()
        return
    down = _git("merge-base", "--is-ancestor", mine, theirs).returncode if up == 1 else up
    if up > 1 or down > 1:
        _note("refs", f"publish: could not compare the store with its mirror (git exit {max(up, down)}); nothing pushed")
    elif down == 0:                                                                      # the store is behind: only adds the newer remote files
        forward(theirs, was=mine)                                                        # a session that commits between the read and the merge is no failure either
    else:                                                                                # diverged
        mt = _git("merge-tree", "--write-tree", mine, theirs)
        if mt.returncode == 0 and mt.stdout.split():
            c = subprocess.run(["git", "-C", str(REPO), "commit-tree", mt.stdout.split()[0], "-p", mine, "-p", theirs, "-m", "board: merge the mirror's commits"],
                               capture_output=True, text=True, env={**os.environ, **_identity()})
            if c.returncode != 0 or not c.stdout.strip():
                _note("merge", f"publish: could not make the merge with the mirror: {(c.stderr.strip().splitlines() or ['no reason given'])[0]}")
            elif forward(c.stdout.strip(), was=mine):                                    # refused where HEAD is no longer `mine`: nothing is lost, the next cycle merges again
                push()
        elif mt.returncode == 1:                                                         # a real conflict: left as it is
            n = _git("rev-list", "--left-right", "--count", f"{mine}...{theirs}").stdout.split()
            local, remote = (n + ["?", "?"])[:2]
            _note("diverged", f"publish: the store and its mirror have diverged and conflict; the live store is left as it is, and it needs a manual merge (local {local} ahead, origin {remote} ahead)")
        else:
            _note("mergetree", f"publish: could not check the store against its mirror (git exit {mt.returncode}); nothing pushed")


class NotServerHost(RuntimeError):
    """The publisher was asked on a box that is not the server host. The message is the one line that says where it runs; nothing was fetched, written, committed or pushed."""


def _server_address() -> str:
    """The address this box's client reaches the server at, as scheme://host[:port] (never a user, a password or a path), or "" when it has none or the address is this box's own (a box that was the server keeps its loopback one)."""
    try:
        from stackshot.fleet import client as _client
        u = urllib.parse.urlsplit(_client.server_url())
        h = u.hostname or ""
        if u.scheme not in ("http", "https") or not h or _agentbox.is_this_box(h):
            return ""
        return f"{u.scheme}://" + (f"[{h}]" if ":" in h else h) + (f":{u.port}" if u.port else "")
    except Exception:  # noqa: BLE001 — the address is a help in the line, never a reason to lose the refusal
        return ""


_SERVING = False      # set by serving(): this process runs the server or its runner


def serving() -> None:
    """Say that this process serves the instance: `stackshot server`, and `stackshot minute` that runs its minute set. Its publishes ask nothing about the host, whatever [release] deploy_ssh calls this box (an
    address or an ssh alias of the server's own box reads as another box). Only those two programs call it, when they start; importing the server's modules does not, so a command or a pass run by hand still asks."""
    global _SERVING
    _SERVING = True


def _check_host(argv: list[str]) -> None:
    """Raise NotServerHost, in a process that is not serving, on a box that is not the server host (config.publish_host_refusal: the rule `./install.sh units` follows). Asked before anything is fetched or written;
    `argv`: the publisher's words to run on the server instead."""
    if not _SERVING and (line := _cfg.publish_host_refusal(argv, _server_address)):
        raise NotServerHost(line)


_RLOCK = threading.RLock()      # this process's threads take turns here; the outermost hold also takes the flock on LOCK, so processes take turns too
_DEPTH = 0                      # how many holds the thread that has _RLOCK has made of it: read and written only while _RLOCK is held


@contextlib.contextmanager
def _locked():
    """The one publish lock. Re-entrant in a thread (a caller that holds `pages_lock()` and calls publish_pages() nests, never waits on itself); the outermost
    hold of the thread that has it also takes the flock on LOCK, so another process (`publish.py publish`, `flush`) waits for it as it always did."""
    global _DEPTH
    with _RLOCK:
        lf = None
        if _DEPTH == 0:
            LOCK.parent.mkdir(parents=True, exist_ok=True)
            lf = open(LOCK, "w")
            try:
                fcntl.flock(lf, fcntl.LOCK_EX)
            except BaseException:
                lf.close()
                raise
        _DEPTH += 1
        try:
            yield
        finally:
            _DEPTH -= 1
            if lf is not None:
                fcntl.flock(lf, fcntl.LOCK_UN)
                lf.close()


def pages_lock():
    """Hold the publish lock across a page's write and its commit, so that no other write or publish lands between them:

        with publish.pages_lock():
            <write the page file>
            publish.publish_pages([path], author)

    publish_pages()'s own hold, taken inside this one, nests."""
    return _locked()


def publish(force_versions: bool = False, host: str = "") -> str:
    """Render + commit + push. Returns the brief's first line."""
    _ro.guard("publish: files, versions, registry, commit and push")
    _check_host(["bump" if force_versions else "publish"])
    with _locked():
        # other writers' commits to the repo arrive through git (the fleet's heartbeats no longer do: fleet.py)
        if _git_on() and not _midway() and _git("fetch", "--quiet", "origin", "main").returncode == 0:
            _git("merge", "--ff-only", "--no-autostash", "--quiet", "origin/main")
        try: _ver.write(force=force_versions)                # installed vs latest for the Machines panel (versions.py; a host is not needed)
        except Exception as e: print(f"versions: {e}", file=sys.stderr)
        try: _pages.cmd_registry(quiet=True)                  # the page registry from the brain mirror, one git pass
        except Exception as e: print(f"registry: {e}", file=sys.stderr)
        r = render_all(str(DATA))                              # one load of the store, both renders
        md = r["full"]
        if len(md) < 200:                                # never overwrite the board with an empty render
            raise RuntimeError(f"render produced {len(md)} md chars — board left untouched")
        tmp = OUT.with_suffix(".md.tmp"); tmp.write_text(md, encoding="utf-8"); os.replace(tmp, OUT)
        first = r["brief"].splitlines()[0].replace("Board: ", "", 1) if md else "board"
        if _git_on(): _gitsync(f"board: {first}", OUT_REL, DATA_REL)
    return first


# ---------------------------------------------------------------------------- a brain's pages ([publish] pages on)
# Only publish_pages() commits a page, and only the files its caller names: nothing here, and nothing in publish(), ever decides on its own that a file under
# pages/ is to be added or removed. Every check on what is named (the paths, the author) is made before anything is staged. The commit is built in an index
# of the call's own (GIT_INDEX_FILE: HEAD read into it, then the named files), never in the store clone's index, which every session on the host shares:
# what a session staged there is never staged, unstaged or committed by a page, and a commit that is not made leaves that index exactly as it was (a
# CommitFailed). Once the commit is made, that index is brought to it for the named files only, as `git commit --only` does; a call that would drop an
# entry a session staged there is refused before the commit. So a failed page is never reported as unchanged and is never taken up later under another
# author's name.

class CommitFailed(RuntimeError):
    """The page files publish_pages() was given were not committed; the message says why. Nothing was staged for them in the store clone's index (the
    commit is built in an index of the call's own); the files on disk are as the caller left them, for the same author to try again."""


_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f<>]|[\ud800-\udfff]")     # control characters (NUL, line breaks, DEL, the C1 set), angle brackets, lone surrogates
_CRUD = " .,:;<>\"\\'"                                               # what git strips from both ends of an identity's name and address (ident.c, crud())
_NAME_LIMIT = 300                                                    # long enough that no real name is cut, short enough that nothing absurd reaches git's argv
_BAD_PATH = re.compile(r"[\x00-\x1f\x7f-\x9f]|[\ud800-\udfff]")      # in a page path: control characters (the C1 set too), and a lone surrogate (a file name that is not UTF-8)
_LIT = "--literal-pathspecs"                                         # every page path is a file name, never a pattern: `a[1].md`, `q?.md`, `*` name themselves
_PATHS_MAX = 1000                                                    # page paths one call takes, and their length in all: every git call's argument list
_PATHS_BYTES = 64 * 1024                                             # stays far below what the system takes


def _clean_name(text: object) -> str:
    """A name as git will write it: every control character, angle bracket and lone surrogate a space, white space runs one space, cut to
    _NAME_LIMIT and stripped at both ends of what git strips there itself. "" when nothing usable is left (".", "...", a DEL, white space)."""
    s = " ".join(_CTRL.sub(" ", text if isinstance(text, str) else "").split())
    return s[:_NAME_LIMIT].strip(_CRUD)


def _clean_mail(text: object) -> str:
    """An address as git will write it: control characters, angle brackets, lone surrogates and white space dropped, cut, git's end characters stripped."""
    s = "".join(_CTRL.sub("", text if isinstance(text, str) else "").split())
    return s[:_NAME_LIMIT].strip(_CRUD)


def _person(author: object, email: object = "") -> str:
    """`Name <address>` for git's --author, made before anything is staged. The name is `author`, cleaned (`_clean_name`); one that cleans to nothing raises
    CommitFailed: a page commit always names who wrote it, never the clone's own user.name. The address: `email`, cleaned, else this process's
    GIT_COMMITTER_EMAIL (the board's own), else a fixed generic one, never the clone's configured user.email (a person's own address, perhaps)."""
    name = _clean_name(author)
    if not name:
        raise CommitFailed(f"the author {str(author)[:80]!r} is no usable name (empty, or only spaces, punctuation or control characters): nothing staged or committed")
    mail = _clean_mail(email) or _clean_mail(os.environ.get("GIT_COMMITTER_EMAIL", "")) or "board@localhost"
    return f"{name} <{mail}>"


def _page_paths(paths: object) -> tuple[str, ...]:
    """The repository paths (`pages/<path>`) of the page paths a caller named, each checked as text before anything is staged. TypeError for one string
    (or path) where a list is meant, or an entry that is no text; CommitFailed for an empty list, for more paths than one call takes (_PATHS_MAX, or
    _PATHS_BYTES of them in all: name them over several calls), and for a path that is empty, holds a control character or a byte that is not UTF-8, or
    has an empty, "." or ".." part (a leading or doubled "/", "../x") or a ".git" part in any case: such a path could reach outside pages/, into a
    repository's own files, or name more than one file. A path named twice counts once."""
    if isinstance(paths, (str, bytes, os.PathLike)):
        raise TypeError("publish_pages: paths is a list of page paths, not one path")
    out: list[str] = []
    for p in paths:
        p = os.fspath(p) if isinstance(p, os.PathLike) else p
        if not isinstance(p, str):
            raise TypeError(f"publish_pages: a page path is text, not {type(p).__name__}")
        if not p or _BAD_PATH.search(p) or any(part in ("", ".", "..") or part.casefold() == ".git" for part in p.split("/")):
            raise CommitFailed(f"the page path {p[:120]!r} is refused (empty, a control character, a file name that is not UTF-8, or an empty, \".\", \"..\" or \".git\" part): nothing staged or committed")
        if (rel := f"{PAGES_REL}/{p}") not in out:
            out.append(rel)
    if not out:
        raise CommitFailed("no page path given: nothing staged or committed")
    if len(out) > _PATHS_MAX or sum(len(r.encode()) + 1 for r in out) > _PATHS_BYTES:
        raise CommitFailed(f"{len(out)} page paths are more than one call takes (at most {_PATHS_MAX}, and {_PATHS_BYTES // 1024} KiB of path text in all): name them over several calls; nothing staged or committed")
    return tuple(out)


def _lstat(rel: str, name: str = "") -> os.stat_result | None:
    """What is at `rel` in the repository (the link itself, never followed), or None when nothing is: it, or a folder above it, is missing. Where it cannot be
    read (a folder with no read or search right, a name too long), CommitFailed naming `name` (or `rel`): unreadable is never taken for missing."""
    try:
        return os.lstat(REPO / rel)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise CommitFailed(f"{(name or rel)[:200]} cannot be read ({e.strerror or type(e).__name__}): nothing staged or committed") from None


def _in_head(rel: str) -> bool:
    return _git("cat-file", "-t", f"HEAD:{rel}").stdout.strip() == "blob"


def _page_changes(rels: tuple[str, ...]) -> tuple[list[str], list[str], list[str]]:
    """(files to add, files to remove, those of the files to remove that are a folder on disk now) of `rels`, read from disk and from HEAD, or CommitFailed
    before anything is staged. A path is a file to add when it is a plain file on disk, one to remove when nothing is on disk there and HEAD has it as a file.
    A file and a folder that swapped places are taken when both sides are named: a path under a folder that is a named file now is a removal (HEAD has it as
    a file), and a named file of HEAD that is a folder now is a removal when a file in that folder is named too (that file's commit removes it). Refused: a
    folder (one path, one file), a symbolic link, a path that runs through a link or through something that is no folder and not named, a folder on the way
    (pages/ included) that is a git repository of its own, a path that cannot be read (never taken for a removal), and a path that is neither on disk nor in
    HEAD (a typo, a doubled "pages/"). So a missing, moved, emptied or linked pages/ never makes more than the named files' removal."""
    named = set(rels)
    adds: list[str] = []
    drops: list[str] = []
    folded: list[str] = []
    for rel in rels:
        parts = rel.split("/")
        gone = False                                                            # a folder above it is missing, or is a named file now
        for i in range(1, len(parts)):                                          # pages/, then every folder between it and the file
            up = "/".join(parts[:i])
            a = _lstat(up)
            if a is None or (stat.S_ISREG(a.st_mode) and up in named):
                gone = True
                break
            if not stat.S_ISDIR(a.st_mode):
                raise CommitFailed(f"{up} is a symbolic link or not a folder: nothing staged or committed")
            if _lstat(f"{up}/.git", up) is not None:
                raise CommitFailed(f"{up} is a git repository of its own (it holds a .git): nothing staged or committed")
        st = None if gone else _lstat(rel)
        if st is not None and stat.S_ISREG(st.st_mode):
            adds.append(rel)
        elif st is None and _in_head(rel):
            drops.append(rel)
        elif st is None:
            raise CommitFailed(f"{rel} is neither a file on disk nor a file in the last commit: nothing staged or committed")
        elif stat.S_ISDIR(st.st_mode) and any(n.startswith(rel + "/") for n in named) and _in_head(rel):
            drops.append(rel)
            folded.append(rel)
        else:
            raise CommitFailed(f"{rel} is a symbolic link or not a file: nothing staged or committed")
    return adds, drops, folded


def _unmerged(rels: tuple[str, ...]) -> None:
    """CommitFailed, before anything is staged, where the index holds one of `rels` (or a file under one) unmerged: a conflict a stash pop or a merge left.
    A `git add` would take the file with its conflict markers as resolved."""
    u = _git(_LIT, "ls-files", "-u", "-z", "--", *rels)
    if u.returncode != 0:
        raise CommitFailed(f"git ls-files failed: {_last_line(u)}: nothing staged or committed")
    if (left := sorted({e.partition("\t")[2] for e in u.stdout.split("\0") if e})):
        raise CommitFailed(f"{_shown(left)} left unmerged (a conflict from a stash pop or a merge): resolve it first; nothing staged or committed")


def _last_line(r: subprocess.CompletedProcess) -> str:
    return (r.stderr.strip().splitlines() or ["no reason given"])[-1]


def _shown(paths: list[str] | tuple[str, ...], most: int = 10) -> str:
    return ", ".join(paths[:most]) + (f" and {len(paths) - most} more" if len(paths) > most else "")


def _page_msg(rels: list[str]) -> str:
    shown = [r.removeprefix(PAGES_REL + "/") for r in rels]
    return "board: page " + ", ".join(shown) if len(shown) <= 3 else f"board: {len(shown)} pages"


def _index_file() -> Path:
    """The store clone's own index file (in a linked worktree, that worktree's), shared with every session on the host."""
    r = _git("rev-parse", "--git-path", "index")
    if r.returncode != 0 or not r.stdout.strip():
        raise CommitFailed(f"git rev-parse failed: {_last_line(r)}: nothing staged or committed")
    return REPO / r.stdout.rstrip("\n")


def _entries(env: dict[str, str]) -> dict[str, tuple[str, ...]]:
    """Every entry of the index `env` names: path -> its `mode object stage` lines."""
    ls = _git("ls-files", "-s", "-z", env=env)
    if ls.returncode != 0:
        raise CommitFailed(f"git ls-files failed: {_last_line(ls)}: nothing committed")
    out: dict[str, list[str]] = {}
    for entry in ls.stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if path:
            out.setdefault(path, []).append(meta)
    return {p: tuple(m) for p, m in out.items()}


def _dropped(tree: str, only: list[str], named: set[str], work: Path) -> list[str]:
    """The entries of the store clone's index, none of them named, that bringing it to `tree` for `only` (what follows the commit) would change: a file a
    session staged where a named file and a folder swap places (a new file staged in a folder that is a named file now, a file staged where a named file
    needs a folder). Tried with git on a copy of that index in `work`, never on the index itself."""
    copy = work / "shared"
    try:
        shutil.copyfile(_index_file(), copy)
    except FileNotFoundError:
        pass                                                                    # no index yet: git reads a missing one as empty
    env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
    before = _entries(env)
    r = _git(_LIT, "reset", "-q", tree, "--", *only, env=env)
    if r.returncode != 0:
        raise CommitFailed(f"git reset failed on a copy of the index: {_last_line(r)}: nothing committed")
    after = _entries(env)
    return sorted(p for p in before.keys() | after.keys() if p not in named and before.get(p) != after.get(p))


def _bring_index(only: list[str], own: dict[str, str]) -> str:
    """Bring the store clone's index to the commit just made, for `only` (what `git commit --only` does to the index it runs on): "" when done, else why
    not. A session's git that holds that index at the moment is waited for, a little."""
    try:
        t = _git("write-tree", env=own)                                          # the call's own index, as committed
        if t.returncode != 0 or not t.stdout.strip():
            return f"git write-tree failed: {_last_line(t)}"
        for wait in (0.1, 0.2, 0.4, 0.8, 0.0):
            r = _git(_LIT, "reset", "-q", t.stdout.strip(), "--", *only)
            if r.returncode == 0:
                return ""
            time.sleep(wait)
        return _last_line(r)
    except Exception as e:  # noqa: BLE001 — the commit is made: said, never raised over it
        return f"{type(e).__name__}: {e}"


@contextlib.contextmanager
def _interrupt_after(held: list[int]):
    """Hold SIGINT back while the block runs: each one is put in `held`, for the caller to raise KeyboardInterrupt once the block is done. An interrupt
    in the middle of a page commit raised inside subprocess.run, which then kills git outright: git's index.lock and next-index-*.lock stayed behind, and
    a commit already made was left with the index not brought to it. Only where SIGINT raises KeyboardInterrupt at all (the main thread, Python's own
    handler); a second SIGINT raises at once (git stopped where it is)."""
    if threading.current_thread() is not threading.main_thread() or signal.getsignal(signal.SIGINT) is not signal.default_int_handler:
        yield
        return
    def hold(signum, frame):
        held.append(signum)
        if len(held) > 1:
            raise KeyboardInterrupt
    prev = signal.signal(signal.SIGINT, hold)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, prev)


def _commit_pages(rels: tuple[str, ...], adds: list[str], drops: list[str], folded: list[str], who: str) -> bool:
    """Commit the removal of `drops` and `adds`, those of `rels` that differ from HEAD, with `who` as the author, built in an index of this call's own (in a
    folder of its own, removed at the end): HEAD read into it, the named files staged there, never in the store clone's index. True: committed; False:
    every one is as HEAD has it. Refused before the commit (CommitFailed, nothing committed, the store clone's index untouched): an entry that is not named
    and would go with them (a file and a folder that swapped places with one side named, a submodule in a folder that is a named file now: `git diff-index`
    is told to show submodules, whatever the config says), and an entry a session staged in the store clone's index that bringing it to the commit would
    drop (`_dropped`). The commit is `git commit --only` of the named files on that index: hooks and signing as for any commit, HEAD as it is at the commit,
    and no automatic maintenance (a gc started from it would read this index, not the store clone's, and could prune a blob only a session's staged entry
    holds). After it the store clone's index is brought to it for the named files (`_bring_index`); where that fails, the commit stays made and stderr says
    what is left and how to clear it."""
    named = set(rels)
    try:
        work = Path(tempfile.mkdtemp(prefix="stackshot-pages-"))
    except OSError as e:                                                        # no room for the call's own folder
        raise CommitFailed(f"{type(e).__name__}: {e}: nothing staged or committed") from e
    own = {**os.environ, "GIT_INDEX_FILE": str(work / "index")}
    try:
        try:
            h = _git("rev-parse", "--verify", "-q", "HEAD^{commit}")
            if h.returncode != 0 or not h.stdout.strip():
                raise CommitFailed(f"git rev-parse failed: {_last_line(h)}: nothing committed")
            head = h.stdout.strip()
            if (r := _git("read-tree", head, env=own)).returncode != 0:
                raise CommitFailed(f"git read-tree failed: {_last_line(r)}: nothing committed")
            if drops and (r := _git(_LIT, "rm", "--cached", "-q", "--ignore-unmatch", "--", *drops, env=own)).returncode != 0:
                raise CommitFailed(f"git rm --cached failed: {_last_line(r)}: nothing committed")
            if adds and (r := _git(_LIT, "add", "--", *adds, env=own)).returncode != 0:
                raise CommitFailed(f"git add failed: {_last_line(r)}: nothing committed")
            d = _git("diff-index", "--cached", "--name-only", "--no-renames", "--ignore-submodules=none", "-z", head, env=own)
            if d.returncode != 0:
                raise CommitFailed(f"git diff-index failed: {_last_line(d)}: nothing committed")
            moved = {p for p in d.stdout.split("\0") if p}
            if (extra := sorted(moved - named)):
                raise CommitFailed(f"{_shown(extra)} would go with {_shown(rels)} and were not named (a file and a folder that swapped places: name both sides): nothing committed")
            changed = [rel for rel in rels if rel in moved]
            if not changed:
                return False
            only = [c for c in changed if c not in folded]
            t = _git("write-tree", env=own)
            if t.returncode != 0 or not t.stdout.strip():
                raise CommitFailed(f"git write-tree failed: {_last_line(t)}: nothing committed")
            if (lost := _dropped(t.stdout.strip(), only, named, work)):
                raise CommitFailed(f"{_shown(lost)}, staged in the store clone's index and not named, would be dropped from it with {_shown(rels)} (a file and a "
                                   "folder that swap places): commit, unstage or name them first: nothing committed")
            r = _git(_LIT, "-c", "maintenance.auto=false", "commit", "--quiet", "--only", "--author", who, "-m", _page_msg(changed), "--", *only, env=own, new_session=True)
            if r.returncode != 0:
                now = _git("rev-parse", "--verify", "-q", "HEAD^{commit}")      # git stopped after the ref moved (a hook ran on, or git was killed): the commit is made
                if now.returncode != 0 or now.stdout.strip() == head:
                    raise CommitFailed(f"git commit failed: {_last_line(r)}: nothing committed")
        except CommitFailed:
            raise
        except Exception as e:                                                  # an OSError (git could not be started), or any other
            raise CommitFailed(f"{type(e).__name__}: {e}: nothing committed") from e
        if (why := _bring_index(only, own)):
            print(f"publish: the page commit is made, and the store clone's index could not be brought to it ({why}): it still holds {_shown(only)} as they "
                  "were before the commit, which reads as staged changes; `git reset -q -- <those files>` in the store clone clears them", file=sys.stderr)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def publish_pages(paths, author: str, email: str = "") -> bool:
    """Commit the page files `paths` names (each relative to pages/: an edit, a new file or a removed one) as one commit, `author` (the signed-in person or
    agent; `email` their address, if known) as the git author and this board's own identity as the committer (a name on the commit, not a signature), then
    push it. Only those files: nothing else under pages/ is ever added, removed or committed. Call it right after the write, under `pages_lock()` where
    another write could land on the same file first.

    True: committed (the push is the board's own: tried at once; a commit that is not on the mirror after it, the push refused or failed, or the fetch
    before it, is said on stderr once an hour and goes out with a later publish: the next one where the branch tracks the mirror, else the next that
    commits; a real conflict with the mirror waits for a manual merge, as the board's own commits do). False: every file named is as the last commit has
    it already. Raises CommitFailed, nothing committed, the store clone's index as it was and the files as they were, when [publish] pages is off (the
    default) or [publish] git is off, for a path or an author refused (checked before anything is staged; see `_page_paths`, `_page_changes`, `_unmerged`,
    `_person`), while the clone is midway through a session's git operation (a merge, a rebase, a detached HEAD), where [paths] repo is a folder inside
    its repository rather than its top, where the store clone's index is locked (an index.lock), where the commit would carry a file not named (a file and
    a folder that swapped places, one side named) or would drop an entry a session staged, or where git refuses or fails a step (a failed sign, a refusing
    hook, git that cannot be started). TypeError for one string where a list is meant. A read-only standby and a box that is not the server host raise as
    publish() does. An interrupt (SIGINT, in the main thread) waits for the commit and the index after it, then raises KeyboardInterrupt saying what was
    made; the push is then the next publish's."""
    _ro.guard("publish pages: commit and push")
    _check_host(["publish"])
    if not _git_on() or not _pages_on():
        raise CommitFailed("pages publishing is off for this board ([publish] pages is not true, or [publish] git is false): nothing staged or committed")
    rels = _page_paths(paths)
    who = _person(author, email)
    with _locked():
        held: list[int] = []
        try:
            with _interrupt_after(held):
                try:
                    if (why := _midway()):
                        raise CommitFailed(f"the store clone is {why}: nothing staged or committed")
                    if (r := _git("rev-parse", "--show-prefix")).returncode != 0:
                        raise CommitFailed(f"git rev-parse failed: {_last_line(r)}: nothing staged or committed")
                    if r.stdout.strip():
                        raise CommitFailed(f"the store clone's path ([paths] repo) is the folder {r.stdout.strip()} inside its repository, not the repository's top: page commits need the top; nothing staged or committed")
                    if (r := _git("var", "GIT_COMMITTER_IDENT")).returncode != 0:
                        raise CommitFailed(f"the board has no committer identity git accepts ({_last_line(r)}): nothing staged or committed")
                    adds, drops, folded = _page_changes(rels)
                    _unmerged(rels)
                    if (lock := Path(f"{_index_file()}.lock")).exists():
                        raise CommitFailed(f"the store clone's index is locked ({lock.name} is there: another git command is running, or one was stopped and left it): nothing staged or committed")
                except OSError as e:                                            # git could not be started: nothing is staged yet
                    raise CommitFailed(f"{type(e).__name__}: {e}: nothing staged or committed") from e
                made = _commit_pages(rels, adds, drops, folded, who)
        except BaseException as e:
            if not held:
                raise
            line = (f"publish: interrupted; no page commit made ({e})" if isinstance(e, CommitFailed) else
                    "publish: interrupted twice; git was stopped where it was, so the page commit may or may not be made and git's index.lock may be left"
                    if len(held) > 1 else f"publish: interrupted, and the page commit raised {type(e).__name__}: {e}")
            print(line, file=sys.stderr)
            raise KeyboardInterrupt(line) from e
        if held:
            line = ("publish: interrupted; the page commit is made, and its push is the next publish's" if made else
                    "publish: interrupted; the named pages are as the last commit has them, nothing committed")
            print(line, file=sys.stderr)
            raise KeyboardInterrupt(line)
        if made:
            try:
                mine = _git("rev-parse", "HEAD").stdout.strip()
                _gitsync("", committed=True)
                if mine and _git("merge-base", "--is-ancestor", mine, "origin/main").returncode != 0:
                    on = _git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
                    where = (f"; the clone is on {on or 'no branch'}, and the push is of main only, so it goes out once main holds it"
                             if on != "main" else "")
                    _note("pages-unpushed", "publish: a page commit is made and is not on the mirror yet (the push or the fetch before it failed or was refused, "
                                            f"or the mirror conflicts){where}; the next publish that pushes takes it")
            except Exception as e:  # noqa: BLE001 — the commit is made and stays True; its push is the next publish's
                _note("pages-sync", f"publish: a page commit is made, and the push step after it failed ({type(e).__name__}: {e}); the next publish that pushes takes it")
        return made


def bump(host: str = "") -> str:
    return publish(force_versions=True, host=host)


def brief() -> str:
    return render(str(DATA), "brief")


# ---------------------------------------------------------------------------- the debounced publish the server makes after a write
# The timer and the lock `_publish` and `_publish_if_idle` share live here; a suite that needs a live or a missing timer sets `_PUB_TIMER` on this module, and one that stubs the publish the Runners panel asks for sets
# `_publish` here too. Server.py calls the same names through its own imports.
_PUB_LOCK = threading.Lock()
_PUB_TIMER: threading.Timer | None = None


def _publish_debounce() -> float:
    return float(_cfg.get("publish", "debounce_seconds", default=5))


def _publish_every() -> float:
    return float(_cfg.get("publish", "every_minutes", default=10)) * 60   # default as in the example


def _publish_now(force_versions: bool = False, host: str = "") -> str:
    if _ro.is_read_only():                  # a standby copy renders in memory when asked (_ro_board), and publishes nothing
        return "(read-only standby: nothing published)"
    try:
        _check_host(["bump" if force_versions else "publish"])
    except NotServerHost as e:     # a pass run by hand off the server host: the debounced publish drops what is returned, so stderr is told too
        _note("host", str(e))
        return f"({e})"               # before the try below: a refused publish writes no roles.json either
    try:
        return publish(force_versions=force_versions, host=host)
    except Exception as e:  # never let a publish failure surface as a tool error
        return f"(publish failed: {e})"
    finally:
        _preg._roles_sync_safe()            # the publish rebuilt the registry; roles.json follows it


def _publish() -> None:
    """Debounced: a burst of writes in one turn publishes once, ~5 s after the first."""
    global _PUB_TIMER
    _board_home_drop()                         # the home is drawn per request: a write is on it at the next read, not at the publish
    if _ro.is_read_only():                  # no timer is started on a standby copy
        return
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return
        _PUB_TIMER = threading.Timer(_publish_debounce(), _publish_now)
        _PUB_TIMER.daemon = True
        _PUB_TIMER.start()


def _publish_if_idle() -> bool:
    """For the Runners panel (runners.ON_CHANGE): True when a publish was scheduled; False while the debounce timer's publish is still running (it stays alive through
    the whole _publish_now, git push included, and _publish returns silently then, so a request made in that time would be lost): the panel asks again a few seconds later."""
    if _ro.is_read_only():
        return True
    with _PUB_LOCK:
        if _PUB_TIMER is not None and _PUB_TIMER.is_alive():
            return False
    _publish()
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "publish"
    if cmd in ("publish", "bump", "flush") and not _ro.is_read_only():      # a standby refuses in its own words (publish's guard)
        try:
            _check_host(a or ["publish"])
        except NotServerHost as e:
            sys.exit(str(e))
    if cmd == "publish":
        print(publish())
    elif cmd == "bump":
        h = a[a.index("--host") + 1] if "--host" in a and a.index("--host") + 1 < len(a) else ""
        print(bump(h))
    elif cmd == "flush":            # reboot hook: last render + board-data commit, pushed; exit 0 only if nothing is left
        print(publish())
        if not _git_on(): print("git is off for this instance ([publish] git = false): nothing to flush"); sys.exit(0)
        dirty = _git("status", "--porcelain", "--", str(DATA)).stdout.strip()
        head = _git("rev-parse", "--short", "HEAD").stdout.strip()
        if "origin" not in _git("remote").stdout.split():      # a local-only data repository: committed is all there is
            if dirty:
                sys.exit(f"board-data not flushed: {len(dirty.splitlines())} uncommitted path(s) (no origin remote)")
            print(f"board-data committed (HEAD {head}); no origin remote, so nothing was pushed"); sys.exit(0)
        f = _git("fetch", "--quiet", "origin", "main")
        if f.returncode != 0:
            why = (f.stderr.strip().splitlines() or ["?"])[-1]
            sys.exit(f"board-data not flushed: cannot fetch main from origin ({why}); {len(dirty.splitlines())} uncommitted path(s)")
        ahead = _git("rev-list", "--count", "origin/main..HEAD").stdout.strip()
        if dirty or ahead not in ("", "0"):
            sys.exit(f"board-data not flushed: {len(dirty.splitlines())} uncommitted path(s), {ahead} commit(s) not pushed")
        print(f"board-data committed and pushed (HEAD {head})")
    elif cmd == "brief":
        sys.stdout.write(brief())
    elif cmd == "render":
        sys.stdout.write(render(str(DATA), a[1] if len(a) > 1 else "full"))
    else:
        sys.exit("usage: publish.py publish | flush | bump [--host H] | brief | render [full|brief] (publish, flush and bump: on the server host only)")
