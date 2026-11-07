#!/usr/bin/env python3
"""puller.py — one machine's fetcher: it asks the stackshot server what waits for the sessions live on this machine and
hands each line to the CLI's own inbox (the design doc). Stdlib only, so
it runs on every box; one per machine, as a user service (Linux) or a scheduled task (Windows).

  puller.py                 run: poll, deliver, confirm, for ever
  puller.py --once          one poll (no waiting), then exit: 0 nothing failed · 1 a delivery failed · 2 the server was not reached
  puller.py --list          the sessions this machine would report, and exit

How it works. The connection goes outward: POST /client/poll with this machine's token, carrying the sessions that are
live here (the CLI's own registry, ~/.claude/sessions/<pid>.json: transcript id, name, Remote Control link, version) and
the machine's facts. That poll is the machine's sign of life and the sessions' heartbeat. The server holds it open until a
line waits for one of those sessions or about 50 s pass, so an idle machine makes about one request a minute and only to
its own server. Each line is written to the session's inbox — a unix socket on Linux, a named pipe with the session's own
token on Windows, the token never leaving the box — and confirmed with POST /client/ack; an unconfirmed line is offered
again. While the server holds deliveries (a reboot's pause) it simply hands nothing out.

Stopping. SIGTERM or SIGINT ends the puller at once, also in the middle of a held poll: a line the server handed out is
only leased until the puller confirms it, so a poll cut short loses nothing (an answer that was already on its way is offered
again when its lease runs out, inbox.LEASE). A delivery under way is finished and confirmed before the puller exits.

Reloading (puller 8). Every cycle the puller reads the VERSION line of its own puller.py on disk (no import). When it differs
from the VERSION this process loaded (provision or a checkout update replaced the file), main() returns RELOAD between two
polls, where nothing is half done, and the entry point runs the file afresh in the same process (runpy; the checkout's
modules the puller imports are dropped from sys.modules first), so a scheduled task or user unit sees its process continue. No
launcher or unit change is needed. A file that is missing, has no VERSION line or does not compile means no reload this tick; a
reload is attempted at most once per RELOAD_MIN_GAP seconds and says so in the log when it holds back. A change to _entry, _fresh,
RELOAD or _RELOAD_FILES itself takes effect only after a real restart: the loop that runs is the one the process started with.

Keeping the box current (puller 9; the PC's helper is its one service, and it keeps its checkout
current). Every poll's answer carries `current`: the server's puller VERSION and checkout commit, and whether this box may
update itself. When the box is BEHIND (its checkout is not at the server's commit) and IDLE (no live session in the CLI's
registry, no claude process), the puller fast-forwards its whole checkout (pages.py, the hooks, everything the box runs from
it, not only this file), then reloads itself (the same RELOAD as above, whether or not the VERSION changed); each attempt is
reported to the server with the next poll (facts.updates); a checkout that reaches the server's commit some other way has an older failure
answered by one ok attempt ("settle" below). This replaces sala's heartbeat pull of the Windows boxes' stackshot
checkout. The puller never updates the Claude CLI: that is the PC's own provisioning. Details at "keeping the box current" below.

Puller 10: the box follows the server through a repo move and a history rewrite with no hand step. The poll's `current` also
carries `repo`, the canonical address of the stackshot repository; a clean, idle box whose origin is another repository takes that
address (fetching from it first), and a clean, idle box whose history is not the server's (a rewrite) saves a rollback branch
`legacy-<short sha>` at its HEAD and moves to the server's commit with `git reset --keep`. A dirty or busy box is still refused.

Options: --registry DIR (the CLI's session registry; default ~/.claude/sessions) · --only NAME|UUID (repeatable: serve
only these sessions, and tell the server the list is partial) · --wait S (how long a poll may be held, default 50) ·
--dry-run (fetch and confirm nothing; print what would be delivered, and what the puller would update now and why not).
The server's address and this machine's token: as client.py finds them ($STACKSHOT_URL, <secrets>/client.url, [client] url;
<secrets>/client.token).
"""
from __future__ import annotations

import ast
import glob
import hashlib
import json
import os
import re
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import client as _client  # noqa: E402  (the address, the token, the POST)
import config as _cfg  # noqa: E402  (ROUTER_CWD_PREFIX; [client] self_update, paths.state)
import said as _said  # noqa: E402  (stdlib only: the transcript's last error, for `stopped`)

# Provision on the Windows boxes restarts the puller task when this differs from the log's last `puller <v>: polling` line: bump it whenever running pullers must pick a change up.
# From 8 on a running puller notices the change itself and reloads (see "Reloading"); a puller older than 8 still needs that one restart.
# A change to _entry, _fresh, RELOAD or _RELOAD_FILES itself takes effect only after a real restart (the running loop is the old one).
VERSION = "10"
WINDOWS = os.name == "nt"
RELOAD = "reload"          # main()'s answer when the checkout's VERSION is not the one loaded: _entry runs the file afresh
RELOAD_MIN_GAP = 600.0     # a reload at most this often (s): a file that keeps differing cannot make a loop
_RELOAD_AT_ENV = "STACKSHOT_PULLER_RELOAD_AT"   # when this process last reloaded (epoch s); the environment outlives the re-run, module state does not
_GATED: set[str] = set()   # reasons already logged for holding a reload back, so the log says each once
_STOP = False
_IN_POLL = False      # True only while the long poll is held: a stop signal then cuts it short (see _Stopped)


class _Stopped(BaseException):
    """Raised by the stop handler inside a held poll. A BaseException, so client.post's own `except Exception` lets it through."""


_VERSION_LINE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)   # the form the provisioning script and clients.puller_current read too
_RELOAD_FILES = ("puller.py", "client.py", "config.py", "said.py")   # the source the puller runs from: all must compile before a reload
_BAD_RELOAD_ENV = "STACKSHOT_PULLER_BAD_RELOAD"   # digest of the files of a reload that failed to load; the environment outlives the re-run, module state does not
_RELOAD_FAIL_PAUSE = 5.0   # s to wait after a reload that failed to load, before the old code polls again
_RELOAD_CRASH_S = 60.0     # a reloaded main() that raises within this long of starting counts as a reload that failed


def disk_version(path: str | None = None) -> str:
    """The VERSION in puller.py on disk, read as text and never imported; "" when the file is missing, unreadable or has no such line."""
    try:
        with open(path or os.path.join(HERE, "puller.py"), encoding="utf-8") as f:
            m = _VERSION_LINE.search(f.read())
    except (OSError, ValueError):
        return ""
    return m.group(1) if m else ""


def _imported(tree) -> set[str]:
    """The top-level module names a parsed file imports, anywhere in it (also inside a function)."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            out.add(n.module.split(".")[0])
    return out


def _walk(read, exists):
    """(name, text, problem) for _RELOAD_FILES and every module of the checkout those import, followed to the end (`read(name)` → the
    text or None; `exists(name)` → whether the checkout has that file). problem is "" for a file that compiles, else SyntaxError,
    ValueError or missing; a file that does not compile is not followed."""
    todo, seen = list(_RELOAD_FILES), set()
    while todo:
        name = todo.pop(0)
        if name in seen:
            continue
        seen.add(name)
        text = read(name); tree = None; bad = ""
        if text is None:
            bad = "missing"
        else:
            try:
                tree = ast.parse(text, name); compile(tree, name, "exec")
            except (ValueError, SyntaxError) as e:
                bad = type(e).__name__
        yield name, text, bad
        if tree is not None:
            todo += [m + ".py" for m in sorted(_imported(tree)) if m + ".py" not in seen and exists(m + ".py")]


def _check_sources(read, exists) -> str:
    """"" when every file the puller runs from compiles, else the first problem as "<file>: <what>". A compile does not run an
    import, but it catches a half-written or broken file, and a missing module one of them imports."""
    for name, _, bad in _walk(read, exists):
        if bad:
            return f"{name}: {bad}"
    return ""


def _compiles(here: str) -> str:
    """The same check on the files on disk in `here`: a checkout caught half way through an update must not be run."""
    def read(name):
        try:
            with open(os.path.join(here, name), encoding="utf-8") as f:
                return f.read()
        except (OSError, ValueError):
            return None
    return _check_sources(read, lambda name: os.path.isfile(os.path.join(here, name)))


def _digest(here: str) -> str:
    """A digest of the files the puller runs from, with every module of the checkout they import, as they are on disk now: what a
    failed reload marks, so that the same files are not tried again, and a later fix to any of them lifts the mark."""
    def read(name):
        try:
            with open(os.path.join(here, name), "rb") as f:
                return f.read().decode("utf-8", "replace")
        except OSError:
            return None
    h = hashlib.sha1()
    for name, text, _ in _walk(read, lambda name: os.path.isfile(os.path.join(here, name))):
        h.update(name.encode() + b"\0" + (text or "-").encode("utf-8", "replace") + b"\0")
    return h.hexdigest()


def reload_due(loaded: str = "", here: str = "", now: float | None = None) -> bool:
    """Should this process reload now: the checkout's puller.py names another VERSION than the one loaded, the files compile, and
    the last reload was RELOAD_MIN_GAP or more ago. False for a missing or unparseable file. Says why it holds back, once per reason."""
    loaded, here = loaded or VERSION, here or HERE
    disk = disk_version(os.path.join(here, "puller.py"))
    if not disk or disk == loaded:
        return False
    if os.environ.get(_BAD_RELOAD_ENV) and os.environ[_BAD_RELOAD_ENV] == _digest(here):
        if _BAD_RELOAD_ENV not in _GATED:
            _GATED.add(_BAD_RELOAD_ENV); print(f"puller {loaded}: checkout has {disk}, but a reload onto these files failed; no reload until they change", file=sys.stderr, flush=True)
        return False
    bad = _compiles(here)
    if bad:
        if bad not in _GATED:
            _GATED.add(bad); print(f"puller {loaded}: checkout has {disk} but does not compile ({bad}); no reload", file=sys.stderr, flush=True)
        return False
    now = time.time() if now is None else now
    try:
        last = float(os.environ.get(_RELOAD_AT_ENV) or 0)
    except ValueError:
        last = 0.0
    if now - last < RELOAD_MIN_GAP:
        if disk not in _GATED:
            _GATED.add(disk); print(f"puller {loaded}: checkout has {disk}, reloaded {int(now - last)} s ago; waiting out {int(RELOAD_MIN_GAP)} s", file=sys.stderr, flush=True)
        return False
    return True


def _fresh(here: str | None = None) -> dict:
    """puller.py run afresh as a module (not __main__), after the checkout's modules are dropped from sys.modules; → its globals."""
    here = here or HERE
    for name, m in list(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if f and name != "__main__" and os.path.dirname(os.path.abspath(f)) == here:
            del sys.modules[name]
    return runpy.run_path(os.path.join(here, "puller.py"), run_name="puller_reloaded")


def _reload_failed(e: BaseException, cur=None) -> None:
    """A reload that did not load (an import error the compile check cannot see) or whose main() raised at once: mark these files so
    that they are not tried again, and record ok=false, reason "reload failed", for the Machines panel. The code that goes on
    (`cur`, possibly an earlier reload's own run of this file, with globals of its own) caches the state file and the checkout's
    commit too: both are dropped there as well, or its next record would overwrite this one. Never raises."""
    try:
        os.environ[_BAD_RELOAD_ENV] = _digest(HERE)
        theirs = getattr(cur, "__globals__", None)
        global _STATE
        _STATE = None                               # the run that failed wrote its attempts to the file; this module's copy is older
        if isinstance(theirs, dict) and theirs is not globals():
            theirs["_STATE"] = None
        last = (attempts() or [{}])[-1]
        _HEAD["at"] = 0.0
        if isinstance(theirs, dict) and isinstance(theirs.get("_HEAD"), dict):
            theirs["_HEAD"]["at"] = 0.0
        _record("stackshot checkout", str(last.get("from") or ""), head() or str(last.get("to") or ""), False, f"{_RELOAD_FAILED}: {type(e).__name__}: {str(e)[:80]}")
        if isinstance(theirs, dict) and theirs is not globals():
            theirs["_STATE"] = None                 # and again: it must read the file with the failure in it
    except Exception as e2:
        print(f"could not record the failed reload: {type(e2).__name__}: {str(e2)[:120]}", file=sys.stderr, flush=True)


def _entry(argv: list[str], first=None) -> int:
    """Run main(); each time it answers RELOAD, run the file afresh and its main() in this same process. A reload that cannot be
    loaded (an import error, a NameError at import: what compile() does not see), or whose main() raises within _RELOAD_CRASH_S
    of starting, is logged and recorded, its files are marked so they are not tried again, and the code that was running goes on
    after a short pause: the supervisor would only start the same broken code again. A RELOAD asked for again while the files are
    still the marked ones (a commit that changed only pages.py, say) is no reason to load them again, nor to end the run: the old
    code goes on, said once. A reloaded main() that crashes after a while ends the run with 1 and the log line, as any crash does:
    the task's trigger or the unit restarts it."""
    cur = first or main
    rc = cur(argv)
    while rc == RELOAD:
        if os.environ.get(_BAD_RELOAD_ENV) and os.environ[_BAD_RELOAD_ENV] == _digest(HERE):   # asked again for files that failed to load: carry on, never exit
            if _BAD_RELOAD_ENV + "-entry" not in _GATED:
                _GATED.add(_BAD_RELOAD_ENV + "-entry"); print("puller: a reload was asked for, but these files failed to load before; the running code goes on", file=sys.stderr, flush=True)
            time.sleep(_RELOAD_FAIL_PAUSE)
            rc = cur(argv)
            continue
        os.environ[_RELOAD_AT_ENV] = str(time.time())
        saved = {n: m for n, m in sys.modules.items() if getattr(m, "__file__", None) and os.path.dirname(os.path.abspath(m.__file__)) == HERE and n != "__main__"}
        try:
            new = _fresh()["main"]
        except Exception as e:                      # the load itself: the old code is still in memory
            print(f"puller reload failed to load: {type(e).__name__}: {e}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            for n, m in list(sys.modules.items()):
                f = getattr(m, "__file__", None)
                if f and n != "__main__" and os.path.dirname(os.path.abspath(f)) == HERE:
                    del sys.modules[n]
            sys.modules.update(saved)
            _reload_failed(e, cur)
            time.sleep(_RELOAD_FAIL_PAUSE)
            rc = cur(argv)
            continue
        t0 = time.time()
        try:
            rc = new(argv)
            cur = new
        except Exception as e:                      # the reloaded main() itself: the traceback says where
            print(f"puller reload failed: {type(e).__name__}: {e}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            if time.time() - t0 >= _RELOAD_CRASH_S:
                return 1
            _reload_failed(e, cur)
            time.sleep(_RELOAD_FAIL_PAUSE)
            rc = cur(argv)
    return rc


def alive(pid) -> bool:
    """Is this pid running. Never os.kill on Windows: with signal 0 it TERMINATES the process there."""
    try:
        pid = int(pid)
    except Exception:
        return False
    if not WINDOWS:
        try:
            os.kill(pid, 0); return True
        except PermissionError:
            return True
        except Exception:
            return False
    import ctypes
    k = ctypes.windll.kernel32                                     # PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally:
        k.CloseHandle(h)


def _router_call(r: dict) -> bool:
    """Is this record the router's own `claude -p` call (router.run_call, also the page-debt call)? It runs in a directory
    `<tmp>/stackshot-router-XXXX` and the CLI registers it like any session, but it is not one."""
    cwd = str(r.get("cwd") or "")
    if not cwd:
        return False
    parent, name = os.path.split(os.path.realpath(cwd))
    return name.startswith(_cfg.ROUTER_CWD_PREFIX) and parent == os.path.realpath(tempfile.gettempdir())


def sessions(reg: str, only: list[str] | None = None) -> list[dict]:
    """The sessions live on this machine, from the CLI's registry: the newest record per transcript id whose process runs.
    The router's own `claude -p` call is not a session and is skipped."""
    best: dict[str, dict] = {}
    for f in glob.glob(os.path.join(reg, "*.json")):
        try:
            r = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        sid = str(r.get("sessionId") or "").lower()
        if not sid or not r.get("messagingSocketPath") or not alive(r.get("pid")) or _router_call(r):
            continue
        if only and r.get("name") not in only and sid not in only:
            continue
        if sid not in best or float(r.get("updatedAt") or 0) > float(best[sid].get("updatedAt") or 0):
            best[sid] = r
    return list(best.values())


_STOPPED: dict[str, tuple[tuple, str]] = {}   # transcript uuid → (the file's signature, why it looks stopped): a transcript is read again only when it changed


def _transcript_roots() -> list[str]:
    roots = list(_said.DEFAULT_ROOTS)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if cfg:
        roots.append(os.path.join(cfg, "projects"))
    return roots


def stopped(sid: str) -> str:
    """Why this session looks stopped, read from its transcript on this machine (puller 7): the last turn ended in an API error
    (a usage or credit limit, the workspace limit), as said.transcript_error reads it; "" when it did not, or when this machine
    holds no transcript for it. The server cannot read a transcript on another machine, so it asks the puller to."""
    try:
        path = _said.find_transcript(sid, _transcript_roots())
        if path is None:
            return ""
        st = path.stat()
    except OSError:
        return ""
    sig = (str(path), st.st_size, st.st_mtime_ns)
    hit = _STOPPED.get(sid)
    if hit is None or hit[0] != sig:
        hit = (sig, _said.transcript_error(path)); _STOPPED[sid] = hit
    return hit[1]


def report(recs: list[dict]) -> list[dict]:
    """What the poll carries per session. name_source is the CLI's nameSource (user, auto, collision, …), so the server can
    tell the CLI's placeholder on a relaunched pane from a name (puller 3); user is this machine's OS username, which
    the CLI's placeholder names are made from ("<user>-<2 hex>"), for the server's shape check (puller 4); stopped is why
    the session's last turn ended in an error, "" when it did not (puller 7), so a pane stopped on any machine counts as stopped."""
    user = _client.os_user()
    return [{"uuid": str(r.get("sessionId")).lower(), "name": str(r.get("name") or ""), "name_source": str(r.get("nameSource") or ""), "user": user,
             "bridge": str(r.get("bridgeSessionId") or ""), "cli": str(r.get("version") or ""), "status": str(r.get("status") or ""),
             "stopped": stopped(str(r.get("sessionId")).lower())} for r in recs]


_VER = {"at": 0.0, "v": "", "sig": None}


def _quiet() -> dict:
    """subprocess kwargs for a child started with no window. pythonw has no console, so a console child (claude.exe) gets a
    fresh one and Windows 11 opens its default terminal for it, which flashes on a desktop on every poll."""
    if WINDOWS:   # CREATE_NO_WINDOW is missing from subprocess off Windows, hence getattr
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000), "stdin": subprocess.DEVNULL}
    return {"stdin": subprocess.DEVNULL}


def _cli_sig():
    """What the installed CLI binary is now (its resolved path, size and mtime), or None when it is not found: an update swaps
    the file, so a change here means the version must be asked again. A stat, cheap enough for every poll."""
    for exe in (shutil.which("claude"), os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.local/bin/claude.exe")):
        try:
            if exe:
                p = os.path.realpath(exe); st = os.stat(p)
                return (p, st.st_size, st.st_mtime_ns)
        except OSError:
            continue
    return None


def cli_version(recs: list[dict]) -> str:
    """The installed CLI's version: the binary's own answer, asked again as soon as the binary changes (an update, so a host's card does not show the old version) and at least every 10 min, else the newest
    a live session reports."""
    sig = _cli_sig()
    if time.time() - _VER["at"] > 600 or (sig is not None and sig != _VER.get("sig")):
        _VER["at"] = time.time(); _VER["sig"] = sig
        for exe in ("claude", os.path.expanduser("~/.local/bin/claude")):
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20, **_quiet()).stdout.strip()
                if out:
                    _VER["v"] = out.split()[0]; break
            except Exception:
                continue
    return _VER["v"] or max((str(r.get("version") or "") for r in recs), default="")


# ---------------------------------------------------------------------------- keeping the box current (puller 9)
# The Windows boxes become thin terminals; stackshot's helper is the PC's one service, and it keeps
# itself current. Until now sala kept a Windows box's ~\stackshot current (its heartbeat fast-forwarded the checkout to
# origin/main every round, and its watchdog provisioned a lagging box over ssh, client.py puller-lag); both retire on sala's
# side, so the puller does the job itself, for the whole checkout: pages.py, the hooks and everything else the box runs from
# it move with this file. The Claude CLI is updated by the PC's own provisioning, not by the puller.
#   behind   the poll's answer carries `current` ({puller, stackshot, self_update}, clients.current): the checkout is behind
#            when the server's commit is not this checkout's HEAD and HEAD is its ancestor (a checkout ahead of the server, or
#            diverged, is left alone).
#   idle     no live session in the CLI's registry (every session on the box, not only the ones served) and no claude process
#            (a `claude -p`: its hooks run from this checkout too). Read-only checks: nothing is ever signalled by process name.
#            On Windows only the CLI's own claude.exe counts (the executable the helper resolves for `claude --version`), not
#            Claude Desktop's; the router's own call is skipped. A tool that fails or times out means busy, with the reason logged.
#            Asked again right before the merge: a box that became busy in the meantime is left alone, and no failure is recorded.
#   once     a target commit is tried once, then again after 1 h, 4 h, and once a day (_BACKOFF): a failure is reported, never
#            looped; a new target starts afresh.
#   how      `git fetch origin`, then `git merge --ff-only <the server's commit>` (a dirty checkout is refused). The
#            server advertises its checkout's HEAD only while origin/main contains it (clients.checkout_commit). Before the fetch, a
#            clean box whose origin is another repository than the one the server publishes (current.repo: a repo move) takes the
#            server's address: the new address is fetched from first (a failure leaves the configuration alone and is the attempt's
#            reason), then `git remote set-url origin`. A clean box whose HEAD is not in origin/main while the server's commit is
#            (history rewritten, a commit never merged, the box's own commits) is moved with `git reset --keep <the server's commit>`,
#            recorded as an attempt (reason "recovered: ...") and under "recovered". The rollback branch `legacy-<short sha>` is
#            created at the old HEAD and must exist BEFORE the reset (a branch that cannot be saved refuses the move). A HEAD that is
#            in origin/main (a box ahead of the server on main) is left alone, one that diverged inside it is refused. The
#            files the puller runs from (_RELOAD_FILES and the modules of the checkout they import) are compiled from git at the
#            target BEFORE the tree is touched, and a target that fails is refused with HEAD where it was. A merge that fails, or
#            whose tree does not compile, is rolled back to the old HEAD with `git reset --keep` (local edits stay; if git
#            refuses, the refusal goes into the attempt's reason, and nothing is ever hard-reset).
#   report   every attempt goes to the server with the next poll as facts.updates, [{what, from, to, ok, at, reason}] (the last
#            10, oldest first; what = "stackshot checkout"; from/to the commits' first 12 characters; at in UTC; reason "" on
#            success), beside facts.stackshot (this checkout's commit, in full): the server keeps the commit on the machine's
#            record beside its CLI version, and the Machines panel keeps the attempts. The card judges the checkout from facts.stackshot
#            against the server's commit (ui.render.machine_alerts): a failed latest attempt shows only while they differ, so the card
#            clears itself when the box is where it should be, whoever or whatever put it there.
#   settle   (the box's own record) the latest attempt of a `what` is what an older puller's card drew, so a failure stayed for as long as nothing newer was recorded.
#            A checkout that reaches the server's commit by another route (a swap for a fresh clone, a checkout or reset by hand)
#            plans nothing, hence records nothing, and would keep showing the failure of an older target. So every poll, when HEAD
#            is the server's commit and the latest attempt for the checkout is a failure, one ok attempt is recorded with the
#            reason "already at the server's commit" (from = to), and the try bookkeeping for the checkout is dropped. Not
#            for a failed reload whose target is HEAD itself (the code at HEAD does not load: that failure is real; a reload
#            that failed on an older commit is stale like any other), not while the tree at HEAD does not compile (a failure
#            saying so is still true), and not counted as a commit the puller moved to ("moved", the stranded recovery): it did
#            not put HEAD there. HEAD is read again right before the record. Once recorded, the latest attempt is ok, so later
#            polls record nothing.
#   restart  after every checkout update (whatever changed: the code the puller runs is the checkout's), by the reload above and
#            on both platforms alike: main() answers RELOAD between two polls and _entry runs the new puller.py in this same
#            process (same pid: a user unit, a scheduled task and its repetition trigger see nothing, no second puller starts).
#            It does not wait for a VERSION change, and the RELOAD_MIN_GAP hold-back does not apply: the update's own backoff
#            (_BACKOFF) is what keeps a box from restarting in a loop. A reload that does not load (an import error, which
#            compile() cannot see) does not end the process, whose supervisor would only start the same code again: _entry logs
#            it, records ok=false "reload failed", marks the files and the modules they import (STACKSHOT_PULLER_BAD_RELOAD, a
#            digest) so reload_due does not retry them, and the code that was running goes on, also when a RELOAD is asked for
#            again while the files are still the marked ones: the run never ends for that.
#   off      the server's [client] self_update = false (its answer then says so; the server never says yes to its own box:
#            deploy.sh keeps that checkout), or the same key = false in this box's own config.
CHECKOUT = HERE                                # the checkout kept current: this file's (a test points it elsewhere)
_BACKOFF = (3600.0, 14400.0, 86400.0)          # s before the 2nd, the 3rd, and every later attempt at the same target version
_UPDATES_KEEP = 10                             # attempts kept on the box and reported
_REACHED = "already at the server's commit"        # the reason of the ok attempt recorded for a checkout that got to the server's commit without the puller
_RELOAD_FAILED = "reload failed"               # the reason's start for a reload that did not load (_reload_failed)
_MOVED_KEEP = 20                               # commits this puller moved HEAD to, kept in its record
_HEAD = {"at": 0.0, "v": ""}
_STATE: dict | None = None                     # <paths.state>/puller-updates.json: {"attempts": [...], "tried": {what: {to, at, n}}, "moved": [the full commits it put HEAD on, last 20], "recovered": [{from, to, at}]}
_SAID: dict = {}                               # what was logged last for a deferral, so it is logged once and again only when it changes
_AHEAD: set = set()                            # the server commits this checkout was found to contain already


def _git(args: list[str], timeout: float = 60, strip: bool = True) -> tuple[int, str, str]:
    """git in CHECKOUT → (exit code, stdout, git's own error line: the first "error:" or "fatal:" line of stderr, else the last line).
    It never prompts (GIT_TERMINAL_PROMPT, and Git Credential Manager's own window: GCM_INTERACTIVE): a credential prompt from a
    scheduled task would hang for ever. `strip=False` returns stdout untouched (for NUL-separated output, whose first path may start with a blank)."""
    git = shutil.which("git")
    if not git:
        return 127, "", "git not found"
    try:
        r = subprocess.run([git, "-C", CHECKOUT, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}, **_quiet())
    except subprocess.TimeoutExpired:
        return 124, "", f"git {args[0]}: no answer in {int(timeout)} s"
    except OSError as e:
        return 126, "", f"git {args[0]}: {e}"
    err = [x.strip() for x in r.stderr.strip().splitlines() if x.strip()]
    line = next((x for x in err if x.startswith(("error:", "fatal:"))), err[-1] if err else "")
    return r.returncode, (r.stdout.strip() if strip else r.stdout), line


def head() -> str:
    """This checkout's commit, asked of git at most every 5 min (and again after a self-update); "" off a git checkout."""
    if time.time() - _HEAD["at"] > 300:
        rc, out, err = _git(["rev-parse", "HEAD"], 20)
        v = out if rc == 0 and re.fullmatch(r"[0-9a-f]{40}", out) else ""
        _HEAD.update(at=time.time(), v=v)
        if not v:                                  # git missing from the PATH, not a repository, "dubious ownership": the box then never updates, so say why
            why = err or (f"git exit {rc}" if rc else "no commit")
            if _SAID.get("head") != why:
                _SAID["head"] = why; print(f"puller {VERSION}: cannot tell this checkout's commit ({why}); it will not update itself", file=sys.stderr, flush=True)
        else:
            _SAID.pop("head", None)
    return _HEAD["v"]


def _short(v: str) -> str:
    return v[:12] if re.fullmatch(r"[0-9a-f]{40}", v or "") else (v or "?")


def _state() -> dict:
    global _STATE
    if _STATE is None:
        try:
            d = json.load(open(_cfg.state("puller-updates.json"), encoding="utf-8"))
        except Exception:
            d = {}
        _STATE = d if isinstance(d, dict) else {}
        _STATE.setdefault("attempts", []); _STATE.setdefault("tried", {})
    return _STATE


def _save_state() -> None:
    p = str(_cfg.state("puller-updates.json")); os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state(), f, indent=1)
    os.replace(tmp, p)


def attempts() -> list[dict]:
    """The attempts this box reports with every poll (facts.updates): the last _UPDATES_KEEP, oldest first."""
    return list(_state()["attempts"])[-_UPDATES_KEEP:]


def _due(what: str, to: str) -> bool:
    """Whether `to` may be tried now: at once for a target not tried yet, else after _BACKOFF since the last try at it."""
    t = _state()["tried"].get(what) or {}
    if t.get("to") != to:
        return True
    n = max(1, int(t.get("n") or 1))
    return time.time() - float(t.get("at") or 0) >= _BACKOFF[min(n, len(_BACKOFF)) - 1]


def _record(what: str, frm: str, to: str, ok: bool, reason: str, reached: bool = False) -> None:
    """Keep one attempt (the last _UPDATES_KEEP are reported). `reached`: not an attempt of this puller's but the finding that the box
    is at the target already (see _settle): it adds no commit to "moved" and leaves no try behind."""
    st = _state(); t = st["tried"].get(what) or {}
    if reached:
        st["tried"].pop(what, None)
    else:
        if ok and what == "stackshot checkout" and re.fullmatch(r"[0-9a-f]{40}", to or ""):   # the commits this puller put HEAD on: the only ones it may move off by itself
            st["moved"] = ([c for c in (st.get("moved") or []) if c != to] + [to])[-_MOVED_KEEP:]
        st["tried"][what] = {"to": to, "at": time.time(), "n": int(t.get("n") or 0) + 1 if t.get("to") == to else 1}
    st["attempts"] = (st["attempts"] + [{"what": what, "from": _short(frm), "to": _short(to), "ok": bool(ok), "reason": reason[:200],
                                         "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}])[-_UPDATES_KEEP:]
    try:
        _save_state()
    except Exception as e:                         # the disk is full or the state directory is not writable: the update happened all the same
        print(f"could not save {_cfg.state('puller-updates.json')}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
    print(f"update {what} {_short(frm)} → {_short(to)}: " + ("ok" if ok else f"FAILED — {reason}"), file=sys.stdout if ok else sys.stderr, flush=True)


_REG = {"dir": None}   # the registry directory main() was given; the router's own claude -p call is found there


def _pk(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _cli_paths() -> set[str]:
    """The CLI binary the helper resolves for `claude --version` (the same lookup as _cli_sig), as comparable paths."""
    out = set()
    for exe in (shutil.which("claude"), os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.local/bin/claude.exe")):
        if exe and os.path.isfile(exe):
            out.add(_pk(exe)); out.add(_pk(os.path.realpath(exe)))
    return out


def _local_dir() -> str:
    """The user's ~/.local, comparable: the native installer keeps the CLI's images under it (an in-place update may rename one)."""
    return _pk(os.path.expanduser("~/.local"))


def _router_pids() -> set[int]:
    """The pids of the router's own `claude -p` calls (the registry lists them; sessions() skips them): not a session on the box."""
    out = set()
    for f in glob.glob(os.path.join(_REG["dir"] or os.path.join(os.path.expanduser("~"), ".claude", "sessions"), "*.json")):
        try:
            r = json.load(open(f, encoding="utf-8"))
            if _router_call(r):
                out.add(int(r.get("pid")))
        except Exception:
            continue
    return out


def _win_claude_procs() -> "list[tuple[int, str]] | str":
    """Windows: [(pid, executable path)] of every claude.exe, from CIM, else wmic; or why neither answered (a str). The path is "" when
    the process would not tell it (that process counts, see _claude_process)."""
    why = ""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40, **_quiet())
        if r.returncode == 0:
            txt = r.stdout.strip()
            d = (json.loads(txt) if txt else None) or []      # PowerShell prints null for nothing
            return [(int(x["ProcessId"]), str(x.get("ExecutablePath") or "")) for x in ([d] if isinstance(d, dict) else d)]
        why = f"powershell exit {r.returncode}"
    except Exception as e:
        why = f"powershell: {type(e).__name__}"
    try:
        import csv, io
        r = subprocess.run(["wmic", "process", "where", "name='claude.exe'", "get", "ProcessId,ExecutablePath", "/format:csv"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40, **_quiet())
        if r.returncode == 0:
            rows = [row for row in csv.DictReader(io.StringIO(r.stdout.strip())) if (row.get("ProcessId") or "").strip().isdigit()]
            return [(int(row["ProcessId"]), (row.get("ExecutablePath") or "").strip()) for row in rows]
        return f"{why}; wmic exit {r.returncode}"
    except Exception as e:
        return f"{why}; wmic: {type(e).__name__}"


def _claude_process() -> str:
    """Why a claude process on the box counts as running, "" when none does: one outside what the registry lists (a `claude -p`, an
    update by hand). A listing only, nothing is ever signalled by process name. On Windows claude.exe is also Claude Desktop, so only
    a process whose executable is the CLI the helper resolves counts (so does one under ~/.local, where an in-place update may have renamed the image, and one whose path cannot be read); the router's own
    call is skipped, as sessions() skips it. A tool that fails, times out or cannot be run means busy, not idle: a box that cannot
    tell is not moved. The reason is what keep_current logs once."""
    try:
        skip = _router_pids()
        if WINDOWS:
            procs = _win_claude_procs()
            if isinstance(procs, str):
                return f"cannot tell whether a claude process runs ({procs})"
            cli = _cli_paths()
            loc = _local_dir()
            mine = [(pid, path) for pid, path in procs if pid not in skip and (not path or not cli or _pk(path) in cli or _pk(path).startswith((loc + "\\", loc + "/")))]
            if not mine:
                return ""
            return f"a claude process is running (pid {mine[0][0]})" + ("" if cli else "; the CLI's own path is not found, so Claude Desktop cannot be told apart")
        r = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=20, **_quiet())
        if r.returncode == 1:
            return ""
        if r.returncode != 0:
            return f"cannot tell whether a claude process runs (pgrep exit {r.returncode})"
        pids = [int(x) for x in r.stdout.split() if x.isdigit() and int(x) not in skip]
        return f"a claude process is running (pid {pids[0]})" if pids else ""
    except Exception as e:
        return f"cannot tell whether a claude process runs ({type(e).__name__}: {str(e)[:80]})"


def busy(recs: list[dict]) -> str:
    """Why the box is not idle, "" when it is: a live session in the CLI's registry, else a claude process."""
    if recs:
        names = sorted(str(r.get("name") or r.get("sessionId") or "?")[:24] for r in recs)
        return f"{len(recs)} live session(s): {', '.join(names[:4])}" + (" …" if len(names) > 4 else "")
    return _claude_process()


def plan(current: dict, recs: list[dict]) -> list[tuple[str, str, str]]:
    """(what, from, to) for what is behind: the checkout, when it is not at the server's commit."""
    out = []
    want, have = str(current.get("stackshot") or ""), head()
    if not re.fullmatch(r"[0-9a-f]{40}", want):    # the server's word goes to git as an argument: only a full sha does
        return out
    if have and want != have and want not in _AHEAD:
        out.append(("stackshot checkout", have, want))
    return out


def _settle(current: dict) -> None:
    """A checkout that is at the server's commit while the latest attempt for it is a failure (it got there another way: swapped for a
    fresh clone, put there by hand) records one ok attempt, so the Machines panel stops drawing an older target's failure; see "settle"
    above. Nothing to do when HEAD is not the server's commit (that failure still stands, and plan() decides what happens to it), when the
    latest attempt is ok or there is none, when it is a failed reload of HEAD itself (the code at HEAD is what failed to load), or when the
    tree at HEAD does not compile (a refusal that says a file does not compile at the commit is still true there)."""
    want = str(current.get("stackshot") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", want) or head() != want:
        return
    last = next((a for a in reversed(_state()["attempts"]) if a.get("what") == "stackshot checkout"), None)
    if not last or last.get("ok") is not False:
        return
    if str(last.get("reason") or "").startswith(_RELOAD_FAILED) and last.get("to") == _short(want):
        return
    if _compiles(CHECKOUT):                        # "" when it compiles, else which file does not
        return
    _HEAD["at"] = 0.0                              # the compile check took time: a checkout moved meanwhile is not recorded as at the server's commit
    if head() == want:
        _record("stackshot checkout", want, want, True, _REACHED, reached=True)


class _Busy(Exception):
    """The box became busy between the idle check and the merge: nothing was done, and it is not a failure."""


def _target_compiles(to: str) -> str:
    """"" when the files the puller runs from compile AT COMMIT `to` (read from git, the tree untouched), else "<file>: <what>"."""
    rc, listing, err = _git(["ls-tree", "--name-only", to], 30)
    if rc != 0:
        return f"{err or 'git ls-tree failed'}"
    names = set(listing.splitlines())
    def read(name):
        rc, out, _ = _git(["show", f"{to}:{name}"], 30)
        return out if rc == 0 else None
    return _check_sources(read, lambda name: name in names)


def _bad_text(bad: str, to: str) -> str:
    name, _, what = bad.partition(": ")
    if not what:
        return f"git ls-tree at {_short(to)}: {name}"
    return f"{name} is missing at {_short(to)}" if what == "missing" else f"{name} does not compile at {_short(to)}"


def _rollback(old: str) -> str:
    """Put the checkout back at `old` after a merge that failed or must not stay: `git reset --keep <old>`, which moves HEAD and
    updates the files that differ between `old` and HEAD, keeps local edits, and refuses (touching nothing) when a file it must
    change has some. Never --hard: someone may be editing a tracked file in the minute since the dirty check. → "" when done, else
    git's reason for refusing, which goes into the attempt's reason."""
    rc, _, err = _git(["reset", "--keep", old], 60)
    _HEAD["at"] = 0.0
    return "" if rc == 0 else f"rollback refused: {err or 'exit ' + str(rc)}"


_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SCP = re.compile(r"(?:[^@/\\:\s]+@)?([A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]):(?![:\\]|//)([^\s]+)")      # git@host:owner/repo (two or more characters before the colon: never a drive letter)


def _address_ok(url: str) -> bool:
    """Whether the server's repo address is one this box will hand to git: one line, no leading dash, and an http(s)/ssh/git/file URL,
    an scp-style address or an absolute path (git's `ext::` and other helpers are no address)."""
    u = str(url or "")
    if not u or u != u.strip() or u.startswith("-") or any(c.isspace() or ord(c) < 32 for c in u):
        return False
    if _SCHEME.match(u):
        return u.split("://", 1)[0].lower() in ("http", "https", "ssh", "git", "file")
    return bool(_SCP.fullmatch(u)) or os.path.isabs(u) or bool(re.match(r"[A-Za-z]:[\\/]", u))


def _repo_id(url: str) -> str:
    """Which repository an address names, the same for its https, ssh and scp forms (host/owner/repo, case folded, no `.git`, no user,
    no port), so a box that reaches the same repository another way is not "moved"; a local path is its absolute, normalised path."""
    u = str(url or "").strip()
    host, path = "", ""
    if _SCHEME.match(u):
        scheme, rest = u.split("://", 1)
        if scheme.lower() == "file":
            return "path:" + os.path.normcase(os.path.abspath(rest.lstrip("/") if re.match(r"/[A-Za-z]:", rest) else rest)).rstrip("/\\")
        netloc, _, path = rest.partition("/")
        host = netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    elif (m := _SCP.fullmatch(u)):
        host, path = m.group(1).lower(), m.group(2)
    else:
        return "path:" + os.path.normcase(os.path.abspath(u)).rstrip("/\\")
    path = path.strip("/")
    path = path[:-4] if path.lower().endswith(".git") else path
    return f"{host}/{path.lower()}"


def _origin_url() -> str:
    rc, out, _ = _git(["remote", "get-url", "origin"], 20)
    return out if rc == 0 else ""


def _clean() -> str:
    """Why the checkout is not clean, "" when it is: a tracked file edited, or a merge, rebase, cherry-pick, revert or bisect in progress
    (read-only: never the index lock from under a session's git). Untracked files are git's to refuse at the move."""
    rc, out, err = _git(["--no-optional-locks", "status", "--porcelain", "--untracked-files=no"], 30)
    if rc != 0:
        return err or "git status failed"
    if out:
        return "local changes in the checkout"
    rc, gd, _ = _git(["rev-parse", "--absolute-git-dir"], 20)
    if rc == 0 and gd:
        for mark in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply"):
            if os.path.exists(os.path.join(gd, mark)):
                return f"a git operation is in progress in the checkout ({mark})"
    return ""


_REPO_WHAT = "repo address"                    # the key of the address change in the try bookkeeping (_due): once, then after 1 h, 4 h, daily
_INCOMING = "refs/stackshot-incoming"          # where a new address is fetched to, before the box has it for its origin


def _drop_incoming() -> None:
    """Remove every ref of the private namespace (a leftover of a run that was killed between its fetch and its cleanup)."""
    rc, out, _ = _git(["for-each-ref", "--format=%(refname)", _INCOMING + "/"], 30)
    for ref in out.split() if rc == 0 else []:
        _git(["update-ref", "-d", ref], 20)


def _switch_origin(want: str, have: str, to: str) -> str:
    """Fetch `want` into a private ref namespace, check that it holds the server's commit `to`, and only then make it origin's address and
    carry the fetched branches over to origin's remote-tracking refs (local ref updates, no second fetch) → "" when done, else why not.
    Nothing of origin's changes before the checks passed. The namespace is emptied before the fetch too, so a leftover ref of a killed run
    cannot make an address look as if it held the commit, and again afterwards. Without a `to` the fetch must still have produced a branch:
    an empty repository is no address to move to."""
    _drop_incoming()
    try:
        rc, _, err = _git(["fetch", "--quiet", "--no-tags", want, f"+refs/heads/*:{_INCOMING}/*"], 180)
        if rc != 0:
            return f"repo address {want}: git fetch: {err or 'exit ' + str(rc)}"
        if to:
            rc, held, _ = _git(["for-each-ref", "--contains", to, "--format=%(refname)", _INCOMING + "/"], 30)
            if rc != 0 or not held:
                return f"repo address {want}: it does not hold the server's commit {_short(to)}"
        else:
            rc, any_ref, _ = _git(["for-each-ref", "--count=1", "--format=%(refname)", _INCOMING + "/"], 30)
            if rc != 0 or not any_ref:
                return f"repo address {want}: it has no branches"
        rc, _, err = _git(["remote", "set-url", "origin", want] if have else ["remote", "add", "origin", want], 20)
        if rc != 0:
            return f"repo address {want}: git remote: {err or 'exit ' + str(rc)}"
        rc, out, _ = _git(["for-each-ref", "--format=%(objectname) %(refname)", _INCOMING + "/"], 30)
        for line in out.splitlines() if rc == 0 else []:
            sha, _, ref = line.partition(" ")
            _git(["update-ref", "refs/remotes/origin/" + ref[len(_INCOMING) + 1:], sha], 20)
        return ""
    finally:
        _drop_incoming()


def _take_repo(want: str, to: str = "") -> tuple[bool, str]:
    """Make this checkout's origin the repository the server publishes (`want`) → (changed, why not): (False, "") when it is that
    repository already, in any form of its address, or the server published none. The new address is fetched from FIRST and must hold the
    server's commit `to` (_switch_origin); only then does it become origin's address, so an address that does not answer, or holds
    another history, leaves the box as it was and the reason is git's or says so. A failure is tried again only after the backoff
    (_BACKOFF, keyed on this address: once, then 1 h, 4 h, daily), also when the failure is an authentication error: until then the
    last reason is the answer, with no network call. The caller has checked that the box is clean and idle."""
    want = str(want or "").strip()
    if not want or not _address_ok(want):
        return False, ""
    have = _origin_url()
    if have and _repo_id(have) == _repo_id(want):
        return False, ""
    tried = _state()["tried"]
    if not _due(_REPO_WHAT, want):
        return False, str((tried.get(_REPO_WHAT) or {}).get("why") or f"repo address {want}: waiting out the backoff after an earlier try")
    why = _switch_origin(want, have, to if re.fullmatch(r"[0-9a-f]{40}", str(to or "")) else "")
    if why:
        t = tried.get(_REPO_WHAT) or {}
        tried[_REPO_WHAT] = {"to": want, "at": time.time(), "n": int(t.get("n") or 0) + 1 if t.get("to") == want else 1, "why": why[:300]}
    else:
        tried.pop(_REPO_WHAT, None)
    try:
        _save_state()
    except Exception as e:
        print(f"could not save {_cfg.state('puller-updates.json')}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
    return (not why), why


def _keep_address(current: dict, recs: list[dict], dry: bool = False) -> None:
    """A box whose origin is not the repository the server publishes (the repo moved) takes the new address while it is clean and idle,
    also when it is at the server's commit already (its next update would otherwise fail on the old address). Said in the log, once
    per reason; a failure here is no update attempt (the next update names it in its own reason if it still matters). Never raises."""
    try:
        want = str(current.get("repo") or "").strip()
        if not want or not _address_ok(want):
            return
        have = _origin_url()
        if not have or _repo_id(have) == _repo_id(want):
            _SAID.pop("repo", None)
            return
        if not dry and not _due(_REPO_WHAT, want):         # a failed try waits out its backoff: no process scan, no network call
            return
        why = busy(recs) or _clean()
        if dry:
            print(f"would take the repo address {want} (now {have})" + (f", but not now: {why}" if why else " now (the box is clean and idle)"), flush=True)
            return
        if why:
            if _SAID.get("repo") != why:
                _SAID["repo"] = why; print(f"repo address {have} → {want}: waiting, {why}", flush=True)
            return
        changed, why = _take_repo(want, str(current.get("stackshot") or ""))
        _HEAD["at"] = 0.0
        said = why or "taken"
        if _SAID.get("repo") != said:
            _SAID["repo"] = said
            print(f"repo address {have} → {want}: " + (f"FAILED, {why}" if why else "ok"), file=sys.stderr if why else sys.stdout, flush=True)
        if changed:
            _SAID.pop("repo", None)
    except Exception as e:
        print(f"repo address check failed: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr, flush=True)


def _save_legacy(old: str) -> tuple[str, str]:
    """The rollback branch for a move off `old`: `legacy-<first 12 characters>` at `old`, made and read back BEFORE anything is reset
    → (branch, why not). An existing branch of that name at `old` is the same save, left as it is; one at another commit (a clash of
    12 characters) gets a time suffix. A branch that cannot be made or read back refuses the move: the old commits stay reachable."""
    name = "legacy-" + old[:12]
    rc, cur, _ = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}"], 20)
    if rc == 0 and cur == old:
        return name, ""
    if rc == 0:
        name += f"-{int(time.time())}"
    rc, _, err = _git(["branch", "--", name, old], 20)
    if rc != 0:
        return "", f"could not save the rollback branch {name}: {err or 'exit ' + str(rc)}"
    rc, cur, err = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}^{{commit}}"], 20)
    if rc != 0 or cur != old:
        return "", f"could not save the rollback branch {name}: it does not read back"
    return name, ""


def _ignored_in_the_way(to: str) -> str:
    """Why the move to `to` would overwrite a file git does not guard, "" when none: an untracked file that .gitignore hides and that
    `to` tracks (git refuses an untracked file in the way, but `reset --keep` and a fast-forward replace an ignored one without a word,
    and it is no commit that a rollback branch could hold). Read-only; a git that cannot answer refuses the move."""
    rc, ign, err = _git(["ls-files", "-z", "--others", "--ignored", "--exclude-standard"], 60, strip=False)
    if rc != 0:
        return f"git ls-files: {err or 'exit ' + str(rc)}"
    if not ign:
        return ""
    rc, diff, err = _git(["diff", "-z", "--name-only", "HEAD", to], 60, strip=False)
    if rc != 0:
        return f"git diff: {err or 'exit ' + str(rc)}"
    guarded = set()                                    # the ignored files, and every folder that holds one (a file of `to` where a folder of ignored files is)
    for f in filter(None, ign.split("\0")):          # -z: a path with a tab, a quote or a newline is one name
        guarded.add(f)
        while "/" in f:
            f = f.rsplit("/", 1)[0]; guarded.add(f)
    hit = sorted(set(filter(None, diff.split("\0"))) & guarded)
    return ("untracked ignored file(s) in the way: " + ", ".join(hit[:5]) + (" …" if len(hit) > 5 else "")) if hit else ""


def _stranded(to: str) -> tuple[str, str]:
    """Whether a clean checkout whose HEAD is not on the server's line is a box to move onto it → ("yes" | "no" | "unknown", why):
    HEAD is not in origin/main and the server's commit `to` is (history rewritten, a branch that was never merged, the box's own
    commits: the old HEAD is saved as a rollback branch before the move). HEAD is tested against the local origin/main first, with
    no network call: in it (an ordinary lag, or a box ahead of the server on main) is "no". Only when the local ref says HEAD is off
    main is origin fetched, so the ref is current before the box is moved. "unknown" (a fetch that failed, or git answering something
    other than yes or no, a timeout included) comes with a "could not tell" reason: the attempt fails, nothing is cached as ahead,
    and the normal backoff tries again. A shallow checkout has its history cut, so ancestry cannot be proved beyond the cut: it is
    refused (red, with the reason) for a server commit that is not the tip of a fetched branch."""
    _HEAD["at"] = 0.0; have = head()
    if not have:
        return "no", ""
    def ancestor(c: str) -> int:
        return _git(["merge-base", "--is-ancestor", c, "refs/remotes/origin/main"], 20)[0]
    def unknown(what: str, rc: int) -> tuple[str, str]:
        return "unknown", f"could not tell whether {what} is in origin/main (git exit {rc})"
    rc = ancestor(have)
    if rc == 0:
        return "no", ""
    if rc != 1:
        return unknown("this checkout", rc)
    frc, out, err = _git(["fetch", "--quiet", "origin"], 120)      # the local ref says off main: make it current before moving the box
    if frc != 0:
        return "unknown", f"could not tell whether this checkout is in origin/main: git fetch: {err or 'exit ' + str(frc)}"
    rc = ancestor(have)
    if rc == 0:
        return "no", ""
    if rc != 1:
        return unknown("this checkout", rc)
    rc = ancestor(to)
    if rc == 0:
        return "yes", ""
    if rc != 1:
        return unknown(f"the server's commit {_short(to)}", rc)
    return "no", ""


def _update_checkout(to: str, still_idle=None, repo: str = "") -> tuple[bool | None, str, bool]:
    """Move the whole of CHECKOUT to the server's commit → (ok, reason, restart needed: True after every update); ok
    None when there is nothing to do (the checkout is ahead already, on main). A dirty checkout is refused: a box someone
    works on is not moved under them. `repo`: the address the server publishes; a box whose origin is another repository takes it
    first (_take_repo). A checkout whose history is not the server's (not in origin/main) is saved as a rollback branch and moved
    with `reset --keep` (_stranded, _save_legacy); one that diverged inside origin/main is refused. The target is compiled from git before the tree is touched (a commit whose puller code does
    not compile is refused, HEAD untouched); `still_idle()` (→ why not, "" when idle) is asked right before the merge, and a box
    that became busy raises _Busy; a merge that fails, or whose result does not compile, is rolled back to the old HEAD (reset --keep: local edits stay)."""
    why = _clean()                             # never the index lock from under a session's git
    if why:
        return False, why, False
    _, why = _take_repo(repo, to)              # the repo moved: the new address, fetched from before it is kept
    if why:
        return False, why, False
    if _git(["cat-file", "-e", to + "^{commit}"], 20)[0] != 0:
        rc, out, err = _git(["fetch", "--quiet", "origin"], 120)
        if rc != 0:
            return False, f"git fetch: {err or 'exit ' + str(rc)}", False
        if _git(["cat-file", "-e", to + "^{commit}"], 20)[0] != 0:
            return False, f"the server's commit {_short(to)} is not on origin", False
    ahead = _git(["merge-base", "--is-ancestor", to, "HEAD"], 20)[0] == 0
    lagging = not ahead and _git(["merge-base", "--is-ancestor", "HEAD", to], 20)[0] == 0
    recover = False
    if not lagging:                            # ahead of the server's commit, or diverged from it: left alone on main, moved onto the server's line when off main
        state, why = _stranded(to)
        if state == "unknown":                 # nothing is remembered as ahead: the backoff tries again
            return False, why, False
        recover = state == "yes"
        if not recover:
            if ahead:
                _AHEAD.add(to)
                return None, "this checkout is ahead of the server's commit", False
            return False, "diverged: this checkout has commits the server's does not", False
    bad = _target_compiles(to)                 # before anything is touched: a broken commit never lands on the box
    if bad:
        return False, _bad_text(bad, to), False
    rc, old, err = _git(["rev-parse", "HEAD"], 20)
    if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", old):
        return False, err or "git rev-parse HEAD failed", False
    why = still_idle() if still_idle else ""
    if why:                                    # the status, the fetch and the checks above took time: a session may have started since
        raise _Busy(why)
    why = _ignored_in_the_way(to)              # before the rollback branch and the move: nothing is changed for a file the move would silently replace
    if why:
        return False, why, False
    # recovery: HEAD is off main, so no fast-forward exists; the rollback branch is made first, then reset --keep moves HEAD and refuses (touching nothing) what would lose an edit or an untracked file
    legacy = ""
    if recover:
        legacy, why = _save_legacy(old)
        if why:
            return False, why, False
    rc, out, err = _git(["reset", "--keep", to] if recover else ["merge", "--ff-only", to], 60)
    if rc != 0:
        reason = f"git {'reset --keep' if recover else 'merge --ff-only'}: {err or 'exit ' + str(rc)}"
        left = _rollback(old)                  # a locked file, an index.lock, a virus scanner may have left it half done
        return False, reason + (f"; {left}" if left else ""), False
    _HEAD["at"] = 0.0; new = head()
    if new != to:
        left = _rollback(old)
        return False, f"still at {_short(new)} after the fast-forward" + (f"; {left}" if left else ""), False
    bad = _compiles(CHECKOUT)                  # the tree as it is now (a checkout filter may differ from git's blobs)
    if bad:
        left = _rollback(old)
        return False, _bad_text(bad, to) + (f"; {left}" if left else ""), False
    if recover:
        _AHEAD.discard(to)
        st = _state(); st.setdefault("recovered", []).append({"from": old, "to": to, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        st["recovered"] = st["recovered"][-_UPDATES_KEEP:]
        return True, f"recovered: left {_short(old)}, which is not in origin/main (saved as {legacy})", True
    return True, "", True


def keep_current(current, recs: list[dict], dry: bool = False, recheck=None) -> int | None:
    """After a poll: update what is behind while the box is idle (the rules above). → RELOAD when the checkout moved and the
    puller must run from it, else None. `recheck()` → the box's live sessions now, asked again right before the merge. Never raises:
    a failure is recorded and reported, and the polling goes on."""
    try:
        if not isinstance(current, dict):
            return None
        if not dry:
            _settle(current)                       # also with the box's updates off or the box busy: it only corrects what is reported
        on = bool(current.get("self_update")) and _cfg.get("client", "self_update", default=True) is not False
        if _SAID.get("mode") != on:
            _SAID["mode"] = on; print(f"keeping this box current: {'on' if on else 'off'}", flush=True)
        if not on:
            return None
        _keep_address(current, recs, dry)          # the repo moved: a clean, idle box takes the new address, also when it is at the server's commit
        todo = plan(current, recs)
        if not todo:
            return None
        rc = None
        for what, frm, to in todo:
            if dry:
                why = busy(recs)
                print(f"would update {what} {_short(frm)} → {_short(to)}" + (f", but not now: {why}" if why else " now (the box is idle)")
                      + ("" if _due(what, to) else " (waiting out the backoff after an earlier try)"), flush=True)
                continue
            if not _due(what, to):                 # in its backoff: the process check is not run on every poll
                continue
            why = busy(recs)
            if why:
                if _SAID.get((what, to)) != why:
                    _SAID[(what, to)] = why; print(f"update {what} {_short(frm)} → {_short(to)}: waiting, {why}", flush=True)
                continue
            try:
                ok, reason, restart = _update_checkout(to, lambda: busy(recheck() if recheck else recs), str(current.get("repo") or ""))
            except _Busy as b:                 # not a failure: nothing was done, no attempt is recorded, the next poll asks again
                if _SAID.get((what, to)) != str(b):
                    _SAID[(what, to)] = str(b); print(f"update {what} {_short(frm)} → {_short(to)}: waiting, {b} (became busy before the merge)", flush=True)
                continue
            if ok is None:
                if _SAID.get((what, to)) != reason:
                    _SAID[(what, to)] = reason; print(f"update {what}: nothing to do, {reason}", flush=True)
                continue
            _record(what, frm, to, bool(ok), reason)
            if ok and restart:
                rc = RELOAD
        return rc
    except Exception as e:
        print(f"update check failed: {type(e).__name__}: {str(e)[:160]}", file=sys.stderr, flush=True)
        return None


_LAST: dict = {"current": None}                    # what the last answered poll said is current (keep_current reads it)


def deliver(rec: dict, text: str, reg: str) -> bool:
    """One line into one session's inbox, as a user turn."""
    line = (json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode()
    path = str(rec.get("messagingSocketPath") or "")
    try:
        if not WINDOWS:
            s = socket.socket(socket.AF_UNIX); s.settimeout(10)
            try:
                s.connect(path); s.sendall(line)
            finally:
                s.close()
            return True
        tok = None                                              # the pipe's token is in the sidecar <pid>.<hash>.key, local to this box
        for kf in glob.glob(os.path.join(reg, f"{rec.get('pid')}.*.key")):
            try:
                tok = json.load(open(kf, encoding="utf-8")).get("peerToken"); break
            except Exception:
                continue
        err = None
        for attempt in range(5):                                # a busy pipe answers "all instances are busy": try again shortly
            try:
                with open(path, "r+b", buffering=0) as p:
                    if tok:
                        p.write((json.dumps({"type": "auth", "token": tok}) + "\n").encode())
                    p.write(line)
                    time.sleep(0.3)
                return True
            except OSError as e:
                err = e; time.sleep(0.5)
        if err is not None:                                     # say why in the log (e.g. 5 access denied: an elevated pane's pipe, a limited puller)
            code = getattr(err, "winerror", None) or err.errno
            print(f"deliver → {rec.get('name') or rec.get('sessionId')}: {code} {err.strerror}", file=sys.stderr, flush=True)
        return False
    except Exception:
        return False


def once(reg: str, only: list[str] | None, wait: float, dry: bool = False) -> int:
    """One poll. → 0 fine · 1 a delivery failed · 2 the server was not reached (or refused)."""
    recs = sessions(reg, only)
    by = {str(r.get("sessionId")).lower(): r for r in recs}
    body = {"sessions": report(recs), "facts": {"claude": cli_version(recs), "platform": sys.platform, "puller_version": VERSION,
                                               "stackshot": head(), "updates": attempts()},
            "wait": 0 if dry else wait, "partial": bool(only)}
    global _IN_POLL
    _IN_POLL = True
    try:
        if _STOP:
            raise _Stopped()
        status, resp = _client.post("poll", body, timeout=wait + 20)
    finally:
        _IN_POLL = False
    if status != 200 or not isinstance(resp, dict):
        print(f"poll failed [{status}]: {str(resp)[:160]}", file=sys.stderr, flush=True); return 2
    _LAST["current"] = resp.get("current")
    ok, bad = [], []
    for d in resp.get("deliveries") or []:
        rec = by.get(str(d.get("session") or "").lower())
        if dry:
            print(f"would deliver to {d.get('name') or d.get('session')}: {str(d.get('text'))[:120]!r}"); bad += d.get("ids") or []; continue
        if rec is not None and deliver(rec, str(d.get("text") or ""), reg):
            ok += d.get("ids") or []
            print(f"delivered → {rec.get('name') or rec.get('sessionId')} ({len(d.get('ids') or [])} line(s), {d.get('src')})", flush=True)
        else:
            bad += d.get("ids") or []
            print(f"FAILED → {d.get('name') or d.get('session')}", file=sys.stderr, flush=True)
    if ok or bad:
        _client.post("ack", {"delivered": ok, "failed": bad}, timeout=20)
    return 1 if (bad and not dry) else 0


def main(argv: list[str]) -> int | str:
    for st in (sys.stdout, sys.stderr):                 # a Windows console or task log is not UTF-8: never fail on an arrow
        try: st.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    a = argv[1:]
    def opt(name, default=None):
        return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default
    reg = opt("--registry", os.path.join(os.path.expanduser("~"), ".claude", "sessions"))
    _REG["dir"] = reg
    only = [a[i + 1] for i, x in enumerate(a) if x == "--only" and i + 1 < len(a)] or None
    wait = float(opt("--wait", "50"))
    if "-h" in a or "--help" in a:
        print(__doc__); return 0
    if "--list" in a:
        for r in sorted(report(sessions(reg, only)), key=lambda r: r["name"]):
            print(f"{r['name']:32} {r['uuid']} {r['cli']:10} {r['status']}")
        return 0
    if "--once" in a or "--dry-run" in a:
        rc = once(reg, only, 0, dry="--dry-run" in a)
        if "--dry-run" in a and rc != 2:          # and the update verdict: what would be updated now, or why not
            keep_current(_LAST["current"], sessions(reg), dry=True)
        return rc

    def stop(*_):
        global _STOP
        _STOP = True
        if _IN_POLL:          # the poll may be held for wait s: end it now (nothing is lost, see "Stopping" above)
            raise _Stopped()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"puller {VERSION}: polling {_client.server_url()} for the sessions in {reg}" + (f" (only {', '.join(only)})" if only else ""), flush=True)
    back = 5.0
    while not _STOP:
        if reload_due():                              # between two polls: nothing is held or half delivered
            print(f"puller {VERSION}: the checkout has {disk_version()}, reloading", flush=True)
            return RELOAD
        try:
            rc = once(reg, only, wait)
        except _Stopped:
            break
        if rc == 2:                                   # the server is away: wait, a little longer each time, at most a minute
            for _ in range(int(back)):
                if _STOP:
                    break
                time.sleep(1)
            back = min(60.0, back * 2)
        else:
            back = 5.0
            if not _STOP and keep_current(_LAST["current"], sessions(reg), recheck=lambda: sessions(reg)) == RELOAD:   # every session on the box counts as busy, not only the ones served
                print(f"puller {VERSION}: the checkout was updated, reloading", flush=True)
                return RELOAD
    print("puller stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(_entry(sys.argv))
