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
TAIL_BYTES = 8 * 1024 * 1024   # of the session's transcript at most this much of its end is read to find a resume of a subagent and the end notices of background tasks
LAST_ROW_BYTES = 16 * 1024     # of the end of a subagent's transcript at most this much is read to see whether its last row is an interruption (a longer last row is none)
RESUME_SLACK_S = 1.0           # a resume dated within this long before the last write of the subagent's meta still counts as newer (the two are stamped by different clocks of one second's grain); a Monitor is read as past its lifetime only this long after it
TASK_START = re.compile(r"Command running in background with ID: (\w+)|Command (?:did not complete within its \d+s timeout and )?was moved to the background \(ID: (\w+)\)|Monitor started \(task (\w+)")      # what a background Bash or a Monitor answers with: a tool result that OPENS with it (a result that only quotes it, a `cat` of another transcript, is no start)
TASK_LIFE = re.compile(r"expires in (?:(\d+)h)? ?(?:(\d+)m)? ?(?:(\d+)s)?|timeout (\d+)ms")      # a Monitor's lifetime, in its start text: `expires in 30m`, `expires in 15m 30s`, `expires in 45s`, `timeout 900000ms`; a Monitor with none lasts until its notice or the window
TASK_NOTE = re.compile(r"<task-id>(\w+)</task-id>((?:(?!<task-id>).){0,1500})", re.S)      # a notice of a task, which ends it only when it carries a `<status>`: a Monitor's per-event notice carries none
TASK_STOP = re.compile(r'"name":\s*"TaskStop",\s*"input":\s*\{\s*"task_id":\s*"(\w+)"')
INTERRUPT = re.compile(r"\[Request interrupted by user(?: for tool use)?\]")      # the text of the last row of a subagent that was stopped
RESUME_KEYS = ("resumedAgentId", "revivedAgentId")      # `revivedAgentId` on Claude Code 2.1.323, both on that version; top-level keys of a user record's `toolUseResult`


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


def _stamp(d: dict[str, Any]) -> float | None:
    """The time (epoch seconds) a record carries, None when it has none or it cannot be read."""
    try:
        return datetime.fromisoformat(str(d.get("timestamp"))).timestamp()
    except (Exception, RecursionError):  # noqa: BLE001
        return None


def _result_texts(d: dict[str, Any]) -> list[str]:
    """The text of each tool result of a user record: the string, or the text blocks of a list, of each."""
    out: list[str] = []
    c = (d.get("message") or {}).get("content")
    for b in c if isinstance(c, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            x = b.get("content")
            if isinstance(x, list):
                x = "".join(str(y.get("text") or "") for y in x if isinstance(y, dict))
            if isinstance(x, str):
                out.append(x)
    return out


def _notice_texts(d: dict[str, Any]) -> list[str]:
    """The strings of a record that can be the notice of a background task: the content of a queue record (a notice the session was handed), the prompt of an attachment (a queued command), and a user message's text (a status
    notice, or a Monitor's expiry event). A tool result is none: it only quotes what a command printed."""
    t = d.get("type")
    if t == "queue-operation":
        c = d.get("content")
        return [c] if isinstance(c, str) else []
    if t == "attachment":
        p = (d.get("attachment") or {}).get("prompt") if isinstance(d.get("attachment"), dict) else None
        return [p] if isinstance(p, str) else []
    if t == "user":
        c = (d.get("message") or {}).get("content")
        if isinstance(c, str):
            return [c]
        return [str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text"] if isinstance(c, list) else []
    return []


def _ending(text: str) -> set[str]:
    """The task ids a text ends: a task notice carrying a `<status>` (completed, failed, stopped), or a Monitor's expiry or end event. A Monitor's per-event notice carries none and ends nothing."""
    return {m.group(1) for m in TASK_NOTE.finditer(text) if "<status>" in m.group(2) or "Monitor expired" in m.group(2) or "Monitor ended" in m.group(2)}


def _life(text: str) -> float | None:
    """A Monitor's lifetime in seconds from the opening of its start text, None when it gives none."""
    m = TASK_LIFE.search(text[:300])
    if m is None:
        return None
    if m.group(4):
        return int(m.group(4)) / 1000.0
    h, mi, s = (int(g or 0) for g in m.groups()[:3])
    return float(h * 3600 + mi * 60 + s) if (h or mi or s) else None


def pending_tasks(tp: Path, now: float | None = None) -> set[str]:
    """The background tasks a subagent started and has no end of in its own transcript: a Bash run in the background (started so, or moved there after its timeout) or a Monitor, whose task id shows in the tool result that
    OPENS with the start text (a result that only quotes it, a `cat` of another transcript, starts nothing), minus the ids a task notice carrying a `<status>` (completed, failed, stopped), a Monitor's expiry event or a TaskStop ended.
    A Monitor's per-event notice carries no status and ends nothing. With `now`, a Monitor is also ended when its start (the record's time) plus its lifetime (`expires in 10m`) plus `RESUME_SLACK_S` is past and the transcript was
    not written after that: its notice may reach only the session's transcript (`read_parent`). A Bash has no lifetime. Only the last `TASK_TAIL_BYTES` are read. An empty set when the file cannot be read."""
    try:
        t = _tail(tp, TASK_TAIL_BYTES)
        at = tp.stat().st_mtime if now is not None else None
    except (Exception, RecursionError):  # noqa: BLE001
        return set()
    started: dict[str, float | None] = {}      # id -> the time its Monitor ends, None for one with no lifetime (or a Bash)
    ended: set[str] = set()
    for line in t.split("\n"):      # a record ends at a newline and nowhere else: `splitlines` also cuts at U+2028, U+0085, a form feed and the like, which JSON leaves raw inside a string, and a record cut there is torn
        if line.startswith('{"type":"api-request'):
            continue      # a request's copy of the conversation: it quotes records, it is none
        if "background" in line or "Monitor started" in line:
            try:
                d = json.loads(line)
                texts = _result_texts(d) if d.get("type") == "user" else []
            except (Exception, RecursionError):  # noqa: BLE001  — a torn line says nothing
                texts = []
            for x in texts:
                m = TASK_START.match(x)
                if m:
                    life, ts = (_life(x), _stamp(d)) if m.group(3) else (None, None)
                    started[next(g for g in m.groups() if g)] = ts + life if life is not None and ts is not None else None
        if "<task-id>" in line:
            try:
                d = json.loads(line)
                for x in _notice_texts(d):
                    ended |= _ending(x)
            except (Exception, RecursionError):  # noqa: BLE001
                pass
    ended |= {m.group(1) for m in TASK_STOP.finditer(t)}
    if at is not None:      # set only when given the clock
        ended |= {i for i, e in started.items() if e is not None and now > e + RESUME_SLACK_S and at <= e + RESUME_SLACK_S}
    return set(started) - ended


def read_parent(tr: Path) -> tuple[dict[str, float], set[str]]:
    """What the session's transcript `tr` says of its subagents, read once from its last `TAIL_BYTES`: ({subagent id: the newest time (epoch seconds) of a resume of it}, {the task ids whose end the session was told}).
    A resume: a SendMessage that woke a subagent answers with `resumedAgentId` (`revivedAgentId` on Claude Code 2.1.323) as a top-level key of the `toolUseResult` of the user record of its result; the same words quoted in a
    tool output or a message, or in a request's copy of the conversation, are none. An end: the notice of a finished subagent's background task is often written only here (a queue record, an attachment, a user message: see
    `_notice_texts`), never to the subagent's own transcript. ({}, set()) when the file cannot be read."""
    out: dict[str, float] = {}
    ended: set[str] = set()
    try:
        for line in _tail(tr, TAIL_BYTES).split("\n"):      # newline only, as above
            if line.startswith('{"type":"api-request') or not ("AgentId" in line or "<task-id>" in line):
                continue
            try:
                d = json.loads(line)
            except (Exception, RecursionError):  # noqa: BLE001  — the first line of the tail may be cut: it says nothing
                continue
            for x in _notice_texts(d) if "<task-id>" in line else []:
                ended |= _ending(x)
            tur = d.get("toolUseResult")
            if d.get("type") != "user" or not isinstance(tur, dict):
                continue
            ts = _stamp(d)
            if ts is None:
                continue      # a record with no readable time says nothing
            for k in RESUME_KEYS:
                i = tur.get(k)
                if isinstance(i, str) and i:
                    out[i] = max(out.get(i, 0.0), ts)
    except (Exception, RecursionError):  # noqa: BLE001
        return {}, set()
    return out, ended


def resumes(tr: Path) -> dict[str, float]:
    """{subagent id: the newest time the session's transcript records a resume of it}: `read_parent`'s first part. {} when the file cannot be read."""
    return read_parent(tr)[0]


def interrupted(tp: Path) -> bool:
    """Is the last row of a subagent's transcript an interruption (a user row whose text is `[Request interrupted by user]`, or `... for tool use]`)? A subagent that was stopped writes nothing after it, and no flag. Only the last
    `LAST_ROW_BYTES` are read: a last row longer than that is none. False when the file cannot be read."""
    try:
        with open(tp, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - LAST_ROW_BYTES))
            raw = f.read()
        d = json.loads(raw.rstrip(b"\r\n ").split(b"\n")[-1])      # a last row that begins before the part read is cut and is no JSON: False below
        c = (d.get("message") or {}).get("content")
        if isinstance(c, list):
            c = "".join(str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        return d.get("type") == "user" and isinstance(c, str) and INTERRUPT.fullmatch(c.strip()) is not None
    except (Exception, RecursionError):  # noqa: BLE001
        return False


def running(session: str, roots: Any, now: float) -> list[dict[str, Any]]:
    """The running subagents of the session (a transcript uuid) as this box holds them: [{"id", "description", "brief", "text", "at"}], `text` the two together, `at` the transcript's last write. A subagent with no
    `finished` flag is running when its transcript was written within `RUNNING_S`, and running but quiet (`"quiet": True`) when it is older than that and no older than `QUIET_CAP_S`: a builder waiting on a long CI or suite
    run writes nothing for a while, and the caller asks only for a pane that is in a turn, so such a subagent is not dropped and the mover's items it is not tied to read unknown, not idle. Past the cap it is dropped.
    [] when the session has no subagents folder or none of them is running. Raises `Unreadable` when the transcript of the session is not on this box or its subagents folder cannot be listed: nothing can be said, and the audit reads that as
    unknown. A subagent whose files cannot be read (a meta that is not JSON, a transcript that cannot be statted or read) is listed as running with no words (`"unreadable": True`) unless its transcript is known to be
    old: it may be running, so it ties to no item and the audit reads the mover as unknown.

    A `finished` flag is not proof that a subagent is done. Claude Code writes `finished: true` into the meta at the end of EVERY turn of a subagent, also when it ends the turn waiting for a background task of its own (a Bash in
    the background, a Monitor), and drops it only when that task's notice, or a SendMessage, wakes the subagent again: a reviewer can end its turn a dozen times in ten hours while it works. A subagent flagged `finished` therefore
    still counts as running (the same entry, `quiet` by the same rule) when EITHER its own transcript holds a background task with no end (`pending_tasks`: started by a tool result that opens with the start text, and not a
    Monitor past its lifetime) and was written within `PARKED_S`, and no notice of that task reached the session's transcript (`read_parent`: the end notice of such a task is often written only there), OR the session's
    transcript holds a resume of it (`toolUseResult.resumedAgentId`, or `revivedAgentId`) dated no earlier than its meta's last write (the meta's mtime; `RESUME_SLACK_S` allowed): the flag is then about to be dropped, or was
    not yet. A subagent with NO flag whose last row is `[Request interrupted by user]` (`interrupted`) was stopped: it is dead, not quiet, unless the session's transcript holds a resume of it dated no earlier than that last
    row (its mtime). The session's transcript is read only for a finished or interrupted subagent, its tail only, once per call; any failure to read either reads as "not parked, not resumed, no notice" (never as
    unreadable). A subagent that ended for good with a task that never reported reads as parked for up to `PARKED_S`: the smaller error, since the audit then reads unknown, not idle."""
    path = _said.find_transcript(session, roots)
    if path is None:
        raise Unreadable("no transcript of the session on this box")
    out: list[dict[str, Any]] = []
    try:
        metas = sorted((path.parent / path.stem / "subagents").glob("agent-*.meta.json"))
    except Exception as e:  # noqa: BLE001
        raise Unreadable(f"the subagents folder cannot be listed ({e.__class__.__name__})") from e
    parent: list[tuple[dict[str, float], set[str]]] = []      # the session's transcript, read once and only when a finished or interrupted subagent needs it

    def told() -> tuple[dict[str, float], set[str]]:
        if not parent:
            parent.append(read_parent(path))
        return parent[0]

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
            if meta.get("finished") is True:
                waiting = pending_tasks(tp, now) if now - at <= PARKED_S else set()
                if waiting:
                    waiting -= told()[1]      # a notice of its task that reached only the session's transcript ends it
                if not waiting and told()[0].get(aid, 0.0) < mp.stat().st_mtime - RESUME_SLACK_S:
                    continue      # finished and neither parked on a task of its own nor resumed since its last write: done
            elif interrupted(tp) and told()[0].get(aid, 0.0) < at - RESUME_SLACK_S:
                continue      # stopped by an interruption and not resumed since its last row: dead, not quiet
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
