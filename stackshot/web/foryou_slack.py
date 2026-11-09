"""foryou_slack.py: the For you list's one Slack hook, the part of the list that needs nothing of server.py: whether a Slack path is configured (`[for_you] slack_command`), the queue and the worker thread
that post an urgent row (so no write waits on a command), and `_for_you_slack_post`, the hook itself.

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The rows a change of an item makes (whether an item is watched, the row a save makes, the due-date pass) are foryou_events.py's,
and they are what call `_foryou_slack` here; what stays in server.py of the list is the close fallback (`_tell_close_owner` and the notices after it, with `_FORYOU_FELL`), which reads foryou_events.py's
`_FORYOU_FAILED`. A suite that stubs the hook (`_for_you_slack_post`, `_for_you_slack_on`) or shortens the command's timeout (`_FORYOU_SLACK_TIMEOUT`) sets it on
this module (`server._fyslack._for_you_slack_post = ...`), the one place the readers look it up: the server's own read of `_for_you_slack_on` goes through the module as well, and is not imported
back. `_foryou_slack` and `_foryou_slack_wait` are imported back by server.py, so `server._foryou_slack` and `server._foryou_slack_wait` stay the names the row and the tests use."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
from typing import Any

from stackshot.core import config as _cfg
from stackshot.web import foryou as _fy

# The Slack post never runs on a thread that does other work (the runner, the /client/message pool): _foryou_slack only queues the
# row, and a worker thread of its own posts it. A post that failed or timed out is tried again by the due-date pass (_foryou_tick), at most
# _fy.SLACK_TRIES times in all and only while the row is under 24 h old; every failure is a stderr line.
_FORYOU_Q: "queue.Queue[int]" = queue.Queue()
_FORYOU_INFLIGHT: set[int] = set()       # row ids queued or being posted: a row is never queued twice
_FORYOU_WLOCK = threading.Lock()
_FORYOU_WORKER: list[threading.Thread] = []
_FORYOU_SLACK_TIMEOUT = 30.0             # seconds a Slack command may run before its whole process group is killed


def _for_you_slack_on() -> bool:
    """Is there a Slack path at all ([for_you] slack_command set)? The scenario suite replaces this with the hook."""
    return bool(str(_cfg.get("for_you", "slack_command") or "").strip())


def _foryou_slack(row: dict[str, Any]) -> None:
    """An urgent row is also posted to Slack, from the worker thread (this only queues it, so no write waits on a command). → nothing."""
    if not _for_you_slack_on():
        return
    rid = int(row["id"])
    with _FORYOU_WLOCK:
        if rid in _FORYOU_INFLIGHT:
            return
        _FORYOU_INFLIGHT.add(rid)
        if not _FORYOU_WORKER or not _FORYOU_WORKER[0].is_alive():
            t = threading.Thread(target=_foryou_slack_work, name="for-you-slack", daemon=True)
            _FORYOU_WORKER[:] = [t]
            t.start()
    _FORYOU_Q.put(rid)


def _foryou_slack_work() -> None:
    while True:
        rid = _FORYOU_Q.get()
        try:
            _foryou_slack_one(rid)
        except Exception as e:  # noqa: BLE001  — the worker never dies on one row
            print(f"for-you: row {rid} Slack worker error: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        finally:
            with _FORYOU_WLOCK:
                _FORYOU_INFLIGHT.discard(rid)
            _FORYOU_Q.task_done()


def _foryou_slack_wait() -> None:
    """Block until the queue is posted (the scenario suite's join; the server never calls it)."""
    _FORYOU_Q.join()


def _foryou_slack_one(rid: int) -> None:
    row = _fy.row_by_id(rid)
    if row is None or row.get("slacked"):
        return                             # marked seen meanwhile, or already posted
    try:
        text = f"[stackshot] For you (urgent): {row['item'] + ' ' if row.get('item') else ''}{row['what']}" + (f" → {row['url']}" if row.get("url") else "")
        err = _for_you_slack_post(text)
    except Exception as e:  # noqa: BLE001
        err = f"{e.__class__.__name__}: {e}"
    tries = _fy.slack_result(rid, not err)
    if err:
        left = "tried again on a later pass" if tries < _fy.SLACK_TRIES else "no more tries"
        print(f"for-you: row {rid} not posted to Slack (try {tries} of {_fy.SLACK_TRIES}, {left}): {err}", file=sys.stderr, flush=True)


def _for_you_slack_post(text: str) -> str:
    """THE SLACK HOOK of the For you list. stackshot has no Slack posting path of its own (anchor-hub only receives Slack, and holds no
    posting credential), and this adds no credential: `[for_you] slack_command` names an argv (a script that already posts, such as the
    one a briefing already uses) that gets the text on its standard input; empty (the default) = no Slack path, the row is on the list only.
    The command runs in a session of its own and its output goes to a file, so a child it leaves behind holds no pipe of ours; past
    _FORYOU_SLACK_TIMEOUT the whole process group is killed. → "" when posted, else why not. The scenario suite replaces this function."""
    import shlex
    cmd = str(_cfg.get("for_you", "slack_command") or "").strip()
    if not cmd:
        return "no Slack path configured ([for_you] slack_command is empty)"
    with tempfile.TemporaryFile() as err:
        try:
            p = subprocess.Popen(shlex.split(cmd), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        except (OSError, ValueError) as e:
            return f"{e.__class__.__name__}: {e}"
        try:
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass                          # it did not read its input; its exit status says how it went
        try:
            p.wait(timeout=_FORYOU_SLACK_TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)      # the group is the command and whatever it started: none outlives the post
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return f"{cmd.split()[0]} did not finish in {_FORYOU_SLACK_TIMEOUT:g} s; killed"
        if p.returncode == 0:
            return ""
        err.seek(0)
        tail = err.read(300).decode("utf-8", "replace").strip().splitlines()
        return f"{cmd.split()[0]} exited {p.returncode}" + (f": {tail[-1]}" if tail else "")
