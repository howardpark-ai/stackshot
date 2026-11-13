"""subagent_tie.py: which running subagent of a mover is at work on WHICH item: the hourly audit's proof that "a subagent is running on it" (audit/hourly.py).

A step status in progress (silence.subagent_running) is something the mover wrote: a claim, and one mover can carry it on several items while one subagent runs. The pane being busy is
the same sort of claim about the mover, not about an item. The audit therefore asks the subagent itself, from the transcript Claude Code keeps on the server's box:

  <root>/<working-directory folder>/<session uuid>/subagents/agent-<id>.meta.json    {"description": "...", "finished": true once it ended, ...}
  <root>/<working-directory folder>/<session uuid>/subagents/agent-<id>.jsonl        its transcript, the first line the brief the mover gave it

`running(session, roots, now)` lists a session's subagents that are running: no `finished` flag and the transcript written within `RUNNING_S`, or a `finished` flag that only says the subagent is PARKED (see `running`). A subagent whose pane was recycled or killed leaves
neither a flag nor a later write, so it stops counting after that window (the same 90 minutes the step status is trusted for: silence.SUBAGENT_S). The caller (server `_mover_subagents`) asks
only for a pane that is busy now, since a subagent keeps its pane in a turn.

`tied(subagents, shown, keys)` says whether one of them is on an item: its description or its brief names the item (its shown id, `board` and `#` and its number, whole: item 12 is not item 123) or a pull request
anchored to the item (`keys`, "owner/repo#n", by its URL or by `PR n` / `#n`, as merge_tie names a pull request for an item that speaks of its repository). A subagent that names neither is on no item the
audit can tell. What that means for an item (audit/hourly.py): a subagent tied to another item leaves this one idle (part F, audit/hand_idle.py, hands it on); a running subagent tied to NONE of the mover's
items (a brief that names no item and no pull request yet, "Build part D") leaves the mover's items UNKNOWN, not idle, since any of them may be what it builds. So does anything that cannot be read: a pane in a turn
whose transcript this box does not hold, a subagents folder that cannot be listed (`Unreadable`), a subagent whose files cannot be read (listed with no words). A mover whose pane is not on this box, or not in a turn,
has no subagent to read: nothing is claimed for it.

Stdlib plus the repo's modules; reads files only."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from stackshot.model import merge_tie as _mt
from stackshot.model import said as _said

RUNNING_S = 90 * 60.0          # a subagent with no `finished` flag counts as running while its transcript was written within this long
QUIET_CAP_S = 6 * 3600.0       # …and, for a mover whose pane is in a turn, as running but quiet (`"quiet": True`: it may wait on a long CI or suite run) until its transcript is this old; past it, it is dropped (a recycled pane leaves no flag)
BRIEF_BYTES = 256 * 1024       # of the first line of its transcript (the brief) at most this many bytes are read
BRIEF_CHARS = 20000            # and at most this many characters of the brief are kept
SKEW_S = 300.0                 # a transcript dated this far ahead of the clock is a skew of clocks, still running
PARKED_S = 90 * 60.0           # a subagent flagged `finished` that waits on a background task of its own counts as running while its transcript was written within this long
TASK_TAIL_BYTES = 32 * 1024 * 1024    # of a subagent's own transcript at most this much of its end is read to find a background task without an end
TAIL_BYTES = 8 * 1024 * 1024   # of the session's transcript at most this much of its end is read to find a resume of a subagent
RESUME_SLACK_S = 1.0           # a resume dated within this long before the last write of the subagent's meta still counts as newer (the two are stamped by different clocks of one second's grain)
TASK_START = re.compile(r"running in background with ID: (\w+)|moved to the background \(ID: (\w+)\)|Monitor started \(task (\w+)")      # what a background Bash or a Monitor answers with
TASK_NOTE = re.compile(r"<task-id>(\w+)</task-id>((?:(?!<task-id>).){0,1500})", re.S)      # a notice of a task, which ends it only when it carries a `<status>`: a Monitor's per-event notice carries none
TASK_STOP = re.compile(r'"name":\s*"TaskStop",\s*"input":\s*\{\s*"task_id":\s*"(\w+)"')
RESUME_ID = re.compile(r'(?:resumed|revived)AgentId\\*"\s*:\s*\\*"(\w+)')      # `resumedAgentId`, and `revivedAgentId` on Claude Code 2.1.323


class Unreadable(Exception):
    """The mover's subagents cannot be told from what this box holds (no transcript for a pane that is in a turn, the subagents folder cannot be read). The audit reads it as UNKNOWN, never as nothing running."""


def _brief(path: Path) -> str:
    """The text of the first message of a subagent's transcript (the brief its mover gave it), "" when it cannot be read: a string, or the text blocks of a list. Any failure reads "" (a deeply nested line is a
    RecursionError, a huge one a MemoryError): the subagent then names nothing it can be tied by, which the audit reads as unknown, not as idle."""
    try:
        with open(path, "rb") as f:
            line = f.readline(BRIEF_BYTES)
        msg = (json.loads(line).get("message") or {}).get("content")
    except (Exception, RecursionError):  # noqa: BLE001
        return ""
    if isinstance(msg, list):
        msg = "\n".join(str(b.get("text") or "") for b in msg if isinstance(b, dict))
    return msg[:BRIEF_CHARS] if isinstance(msg, str) else ""


def _tail(path: Path, n: int) -> str:
    """The last `n` bytes of a file as text (the whole file when it is smaller). OSError when it cannot be read."""
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - n))
        return f.read().decode("utf-8", errors="replace")


def pending_tasks(tp: Path) -> set[str]:
    """The background tasks a subagent started and has no end of in its own transcript: a Bash run in the background (started so, or moved there after its timeout) or a Monitor, whose task id shows in the tool result, minus the ids
    a task notice carrying a `<status>` (completed, failed, stopped) or a TaskStop ended. A Monitor's per-event notice carries no status and ends nothing. Only the last `TASK_TAIL_BYTES` are read. An empty set when the file cannot be read."""
    try:
        t = _tail(tp, TASK_TAIL_BYTES)
    except (Exception, RecursionError):  # noqa: BLE001
        return set()
    started = {next(g for g in m.groups() if g) for m in TASK_START.finditer(t)}
    if not started:
        return set()
    ended = {m.group(1) for m in TASK_NOTE.finditer(t) if "<status>" in m.group(2) or "Monitor expired" in m.group(2) or "Monitor ended" in m.group(2)}
    ended |= {m.group(1) for m in TASK_STOP.finditer(t)}
    return started - ended


def resumes(tr: Path) -> dict[str, float]:
    """{subagent id: the newest time (epoch seconds) the session's transcript `tr` records a resume of it}: a SendMessage that woke it answers with `resumedAgentId` (`revivedAgentId` on Claude Code 2.1.323) in the record of its
    result. Only a user record counts (a tool result), so a message that merely quotes the words does not, and only the last `TAIL_BYTES` of the file are read, once. {} when the file cannot be read."""
    out: dict[str, float] = {}
    try:
        tail = _tail(tr, TAIL_BYTES)
        for line in tail.splitlines():
            if "AgentId" not in line:
                continue
            ids = RESUME_ID.findall(line)
            if not ids:
                continue
            try:
                d = json.loads(line)
                if d.get("type") != "user":
                    continue
                ts = datetime.fromisoformat(str(d.get("timestamp"))).timestamp()
            except (Exception, RecursionError):  # noqa: BLE001  — the first line of the tail may be cut, one that is no record or has no time says nothing
                continue
            for i in ids:
                out[i] = max(out.get(i, 0.0), ts)
    except (Exception, RecursionError):  # noqa: BLE001
        return {}
    return out


def running(session: str, roots: Any, now: float) -> list[dict[str, Any]]:
    """The running subagents of the session (a transcript uuid) as this box holds them: [{"id", "description", "brief", "text", "at"}], `text` the two together, `at` the transcript's last write. A subagent with no
    `finished` flag is running when its transcript was written within `RUNNING_S`, and running but quiet (`"quiet": True`) when it is older than that and no older than `QUIET_CAP_S`: a builder waiting on a long CI or suite
    run writes nothing for a while, and the caller asks only for a pane that is in a turn, so such a subagent is not dropped and the mover's items it is not tied to read unknown, not idle. Past the cap it is dropped.
    [] when the session has no subagents folder or none of them is running. Raises `Unreadable` when the transcript of the session is not on this box or its subagents folder cannot be listed: nothing can be said, and the audit reads that as
    unknown. A subagent whose files cannot be read (a meta that is not JSON, a transcript that cannot be statted or read) is listed as running with no words (`"unreadable": True`) unless its transcript is known to be
    old: it may be running, so it ties to no item and the audit reads the mover as unknown.

    A `finished` flag is not proof that a subagent is done. Claude Code writes `finished: true` into the meta at the end of EVERY turn of a subagent, also when it ends the turn waiting for a background task of its own (a Bash in
    the background, a Monitor), and drops it only when that task's notice, or a SendMessage, wakes the subagent again: a reviewer can end its turn a dozen times in ten hours while it works. A subagent flagged `finished` therefore
    still counts as running (the same entry, `quiet` by the same rule) when EITHER its own transcript holds a background task with no ending notice (`pending_tasks`) and was written within `PARKED_S`, OR the session's transcript
    holds a resume of it (`resumes`) dated no earlier than its meta's last write (the meta's mtime; `RESUME_SLACK_S` allowed): the flag is then about to be dropped, or was not yet. The session's transcript is read only for a
    finished subagent with no task pending, and its tail only, once per call; any failure to read either reads as "not parked, not resumed" (never as unreadable). A subagent that ended for good with a task that never reported
    reads as parked for up to `PARKED_S`: the smaller error, since the audit then reads unknown, not idle."""
    path = _said.find_transcript(session, roots)
    if path is None:
        raise Unreadable("no transcript of the session on this box")
    out: list[dict[str, Any]] = []
    try:
        metas = sorted((path.parent / path.stem / "subagents").glob("agent-*.meta.json"))
    except Exception as e:  # noqa: BLE001
        raise Unreadable(f"the subagents folder cannot be listed ({e.__class__.__name__})") from e
    resumed: dict[str, float] | None = None      # the session's resumes, read once and only when a finished subagent has no task pending
    for mp in metas:
        aid = mp.name[len("agent-"): -len(".meta.json")]
        try:
            tp = mp.with_name(mp.name[: -len(".meta.json")] + ".jsonl")
            at = tp.stat().st_mtime
            if not (-SKEW_S <= now - at <= QUIET_CAP_S):
                continue      # past the cap (a recycled pane leaves no flag), or dated further ahead than a skew of clocks: not running, whatever the meta says
            meta = json.loads(mp.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                raise ValueError("meta is not an object")
            if meta.get("finished") is True and not (now - at <= PARKED_S and pending_tasks(tp)):
                if resumed is None:
                    resumed = resumes(path)
                if resumed.get(aid, 0.0) < mp.stat().st_mtime - RESUME_SLACK_S:
                    continue      # finished and neither parked on a task of its own nor resumed since its last write: done
            desc, brief = str(meta.get("description") or ""), _brief(tp)
            out.append({"id": aid, "description": desc, "brief": brief, "text": f"{desc}\n{brief}", "at": at, **({"quiet": True} if now - at > RUNNING_S else {})})
        except (Exception, RecursionError):  # noqa: BLE001  — any failure on one subagent's files: it may be running, and nothing can be tied to it
            out.append({"id": aid, "text": "", "at": 0.0, "unreadable": True})
    return out


def _names_pr(text: str, key: str, bare: bool = True) -> bool:
    """Does `text` name the pull request `key` ("owner/repo#n"), and in the key's own repository? By its URL, or written out as `owner/repo#n`, always; by its number alone (`PR n`, `#n`) only when `bare` and the text names no pull
    request of the same number in another repository by URL (then the number is that one's): a bare number is the repository's of the item it is anchored to, never any repository's."""
    k = key.lower()
    repo, _, n = k.rpartition("#")
    if not (repo and n):
        return False
    if _mt.names(text, k):      # its URL (the number alone is not asked here)
        return True
    if re.search(r"(?<![\w./-])" + re.escape(k) + r"(?!\w)", text, re.I):      # `owner/repo#n` written out
        return True
    if not bare:
        return False
    if any(m.group(2) == n and m.group(1).lower() != repo for m in _mt.PR_URL.finditer(text)):
        return False      # the text gives this number's pull request by URL, in another repository
    return _mt.names(text, k, [repo])


def names_item(text: str, shown: str, keys: Iterable[str] = (), no_bare: Iterable[str] = ()) -> bool:
    """Does `text` name the item (its shown id, whole and in any case) or a pull request anchored to it (`keys`, "owner/repo#n")? A pull request is named by its URL or as `owner/repo#n`, and by `PR n` / `#n` (the
    item speaks of that repository: a pull request of it is anchored to the item) only in the item's own repository: a number whose URL in the text is in another repository is that repository's, and a key in `no_bare`
    (lower-case) is named by its URL or its full form alone."""
    t = str(text or "")
    if shown and re.search(r"(?<![\w#])" + re.escape(shown) + r"(?![\w])", t, re.I):
        return True
    off = {str(x).lower() for x in no_bare}
    return any(_names_pr(t, k, k.lower() not in off) for k in keys if k)


def _clashing(candidates: dict[str, tuple[str, Iterable[str]]]) -> set[str]:
    """The pull request keys (lower-case) of the candidates that share a number with a key of another repository: `PR 5` alone cannot say which of two repositories' pull request 5 a subagent means."""
    by_n: dict[str, set[str]] = {}
    for _shown, keys in candidates.values():
        for k in keys or ():
            if k:
                repo, _, n = str(k).lower().rpartition("#")
                by_n.setdefault(n, set()).add(repo)
    return {f"{repo}#{n}" for n, repos in by_n.items() if len(repos) > 1 for repo in repos}


def tied_to(sub: dict[str, Any], candidates: dict[str, tuple[str, Iterable[str]]]) -> set[str]:
    """The candidates ({id: (its shown id, its anchored pull requests)}) a running subagent is tied to: those its DESCRIPTION names; only when the description names none, those its brief names. A brief that merely mentions
    an item ("a follow-up of item X") must not tie the subagent to it when the description already says what it works on. A subagent given with a `text` alone (no `description` key) reads that text as its description.
    A pull request number written alone ties only when it is no other candidate's number in another repository (`_clashing`): two items anchored to `a/x#5` and `b/y#5` are told apart by the URL or `owner/repo#n` form."""
    desc = str(sub.get("description") if "description" in sub else sub.get("text") or "")
    clash = _clashing(candidates)
    for words in (desc, str(sub.get("brief") or "")):
        hit = {g for g, (shown, keys) in candidates.items() if names_item(words, shown, [k for k in keys if k], clash)}
        if hit:
            return hit
    return set()


def tied(subagents: Iterable[dict[str, Any]], shown: str, keys: Iterable[str] = ()) -> bool:
    """Is one of the running `subagents` (from `running`) at work on the item (by `tied_to` with the item as the only candidate): its description, else its brief, names the item or a pull request anchored to it."""
    return any(tied_to(s, {"": (shown, keys)}) for s in subagents or ())
