"""merge_log.py: the hub's record of the pull requests it saw merge, read by the server's progress clock (`server._merge_progress_tick`).

Why a file of its own. The hub notices a pull request closing as merged at its source, from a read it makes anyway (an anchored pull request's own poll, a thread of a repository anchor's
notifications), and that read already holds the pull request's body. The routing log does not carry the event in one shape (a routine event on the fleet's own pull request is logged with no
event type, a direct anchor's with none either, a burst joins its types), and a notice has no room for the body. So `Hub.emit`, the one funnel every event passes before it takes any of those
lanes, appends one line here for a merge: no second read of GitHub, nothing for a session to receive, nothing a router rules on.

One line per merge: {"ts": when the hub saw it, "repo": "owner/repo" as the anchor names it, "n": the pull request's number, "refs": ["board#N", ...] the board ids its body names (at most 10)}.
The server reads it from a byte offset it keeps and finishes a line only when its newline is there, so a line the hub is still writing is read next time. The file only grows (a line is about
100 bytes: a year of merges is well under a megabyte); the server skips a line older than it counts.

Pure apart from the file: no server import, no clock read (the caller passes `now`)."""
from __future__ import annotations

import json
import re
import reprlib
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

BOARD_REF = re.compile(r"(?<![\w/#-])board#([1-9]\d*)\b", re.I)      # the board's own id form, the fallback when model/ids.py cannot be imported; a bare "#n" in a body is a pull request or an issue of the repository
_REF_OK = re.compile(r"[\w#-]{2,80}")      # what a stored ref may look like: an item id as written, never free text
_IDS: list[Any] = []      # model/ids.py, imported at the first body read (it brings fastmcp: the hub that never reads a merged pull request's body never pays for it)
MAX_REPO = 140      # GitHub's longest "owner/repo": 39 + 1 + 100 (the writers and `normal` share it: a line the reader would refuse is never written)
MAX_NUMBER = 10**9      # a pull request number past a billion is no number of GitHub's: it would only ride into merged_seen and a History line
_DIGITS = len(str(MAX_NUMBER))      # the longest run of digits a number may be written with (the bound is checked in `_bounded`)
_PART = rf"[\w.-]{{1,{MAX_REPO}}}"      # one side of "owner/repo", bounded like the whole (`_bounded` checks the sum)
_GITHUB_PATH = re.compile(rf"github\.com/({_PART}/{_PART})/(?:pull|issues)/(\d{{1,{_DIGITS}}})(?!\d)", re.I)
_ANCHOR = re.compile(rf"^github:({_PART}/{_PART})#(\d{{1,{_DIGITS}}})$", re.I)
MAX_REFS = 10


def path() -> Path:
    return _cfg.state("merges.jsonl")


def _ids() -> Any:
    if not _IDS:
        try:
            from stackshot.model import ids as m  # noqa: PLC0415
            _IDS.append(m)
        except Exception:  # noqa: BLE001  — the body is read with the board's own form alone, never lost to an import
            _IDS.append(None)
    return _IDS[0]


def refs(body: Any) -> list[str]:
    """The item ids a pull request's body names as plain words, in the order written, each once (at most MAX_REFS), as written and lower-case: board#N, a temporary id, a legacy gNN id, an item
    page link (/items/<n> as board#<n>). Read as a session's message is (model/ids.py): code fences, inline code and quoted text are blanked first, an id with something glued on is no id, and the merge
    queue's "group g7" forms are no item. The server resolves each with its own `_norm_id` and keeps those that name an open item."""
    ids = _ids()
    out: list[str] = []
    if ids is None:
        found = [f"board#{m.group(1)}" for m in BOARD_REF.finditer(str(body or ""))]
    else:
        found = []
        for m in ids._ITEM_REF.finditer(ids._without_mq_groups(ids._plain_text(str(body or "")))):
            ref = (m.group(1) or m.group(2) or "").lower()
            found.append(f"board#{ref}" if m.group(2) and ref.isdigit() else ref)
    for ref in found:
        if ref not in out:
            out.append(ref)
    return out[:MAX_REFS]


def _bounded(repo: str, n: int) -> tuple[str, int]:
    """(repo, n) when `normal` would accept them on read (a repository of at most MAX_REPO characters, a number from 1 to MAX_NUMBER), else ("", 0): the writers never write a line the reader refuses."""
    return (repo, n) if len(repo) <= MAX_REPO and 0 < n <= MAX_NUMBER else ("", 0)


def pull_of(anchor: str, url: str = "") -> tuple[str, int]:
    """The pull request an event is about, as ("owner/repo", n): the anchor's own id (`github:owner/repo#n`), else the repository and number in the event's link (a pull request's page, or a
    comment on it); ("", 0) when neither says (a release, a repository's notifications with no thread link) or when what it names is past the caps `normal` applies on read (a repository longer than
    MAX_REPO, a number above MAX_NUMBER): such an event is no line, never one the reader would refuse."""
    m = _ANCHOR.match(str(anchor or "").strip())
    if m:
        return _bounded(m.group(1).lower(), int(m.group(2)))
    m = _GITHUB_PATH.search(str(url or ""))
    return _bounded(m.group(1).lower(), int(m.group(2))) if m else ("", 0)


def is_merge(etype: Any) -> bool:
    """Does the event's type (the hub's `etype`, several joined with "+") say a pull request merged?"""
    return "pr_merged" in [t for t in str(etype or "").split("+") if t]


def line_for(anchor: str, url: str, etype: Any, body_refs: Any, now: float) -> dict[str, Any] | None:
    """The line for an event, None when it is no merge or names no pull request."""
    if not is_merge(etype):
        return None
    repo, n = pull_of(anchor, url)
    if not repo or n <= 0:
        return None
    return {"ts": round(float(now), 3), "repo": repo, "n": n, "refs": [str(r) for r in (body_refs or []) if _REF_OK.fullmatch(str(r))][:MAX_REFS]}


def append(line: dict[str, Any], file: Path | None = None) -> None:
    """Add one line (one write of a line shorter than a pipe's buffer, so two processes never interleave one). `file`: another log of the same shape (event_log.py), default the merge log."""
    p = file or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    row = (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8")
    with open(p, "ab+") as f:      # appends always land at the end; the read is only to see the last byte
        if f.seek(0, 2) > 0:      # a file that does not end with a newline (a torn write, a hand edit): this line starts on a line of its own, never glued to the last
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                row = b"\n" + row
        f.write(row)


def note(anchor: str, url: str, etype: Any, body_refs: Any, now: float) -> bool:
    """The hub's call for each event: a line when it is a merge. → whether a line was written."""
    line = line_for(anchor, url, etype, body_refs, now)
    if line is None:
        return False
    append(line)
    return True


def size() -> int:
    """The file's size in bytes, 0 when there is none."""
    try:
        return path().stat().st_size
    except OSError:
        return 0


def normal(row: dict[str, Any]) -> dict[str, Any]:
    """A line as the server uses it: {"ts": float, "repo": "owner/repo", "n": int > 0, "refs": [str]}. Raises for a line of the wrong shape (a hand edit, a torn write that still parsed): ValueError for
    a wrong value (a repo that is not "owner/repo" or is longer than MAX_REPO, a number below 1 or above MAX_NUMBER, a time that is not finite), TypeError for a wrong type (a repo that is not text, a
    number or time that is a list or an object), OverflowError for a number that does not fit (n=1e999, a time of 400 digits), KeyError for a missing repo or number. The caller catches every Exception, skips
    the line and logs it (`shown`, never `str`: a RecursionError from a hand-built structure is caught the same way). A ref that is not a string is left out, so a line whose refs nest deeper than str() can follow
    costs nothing; a repo that is not text is refused before it is turned into text, so a deep one costs nothing either."""
    raw = row["repo"]
    if not isinstance(raw, str):
        raise TypeError(f"repo is a {type(raw).__name__}, not text")
    repo, n, ts = raw.strip().lower(), int(row["n"]), float(row.get("ts") or 0)
    if len(repo) > MAX_REPO or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not 0 < n <= MAX_NUMBER or ts != ts or ts in (float("inf"), float("-inf")):
        raise ValueError(f"not a merge line: repo={repo[:40]!r}{' (cut)' if len(repo) > 40 else ''} n={str(n)[:12]} ts={ts}")
    rs = row.get("refs")
    return {"ts": ts, "repo": repo, "n": n, "refs": [r for r in rs if isinstance(r, str) and _REF_OK.fullmatch(r)][:MAX_REFS] if isinstance(rs, list) else []}      # a ref is a string: anything else (a number, a nested list or object, however deep) is no ref and is never turned into text


def shown(x: Any, cap: int = 80) -> str:
    """A look at anything for a log line, at most `cap` characters (the one helper for a line read from a log file: event_log.shown is this with its own cap). reprlib limits the depth and the size of each
    part, so a huge or deep value never builds a huge string, and if even that fails (a structure too deep for it, an object whose repr raises) the class name stands in, read with `type()` and not
    `.__class__`, which an object can make raise. Never `str(row)` for a line read from the file: a hand-made line can nest deeper than str() can follow."""
    try:
        return reprlib.repr(x)[:cap]
    except Exception:  # noqa: BLE001  — RecursionError and a hostile __repr__ included
        return f"<{type(x).__name__}>"[:cap]


def read(offset: int = 0, file: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    """The lines from byte `offset` on, and the offset after the last whole line read. A file that is shorter than `offset` (replaced) is read from its start; a missing one reads as nothing.
    A line that is not JSON, is nested too deep to parse (RecursionError) or is not an object with a repository and a number (`{}`, `[1]`, a number of 0, an empty repository) is skipped without a log line (the offset still moves past it) and the rest are read; a line
    that has a repository and a number but is of the wrong shape is found later, by `normal`, and logged by the caller. `file`: another log of the same shape (event_log.py), default the merge log."""
    try:
        with open(file or path(), "rb") as f:
            size = f.seek(0, 2)
            if offset > size or offset < 0:
                offset = 0
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], max(int(offset), 0)
    cut = data.rfind(b"\n") + 1
    rows: list[dict[str, Any]] = []
    for raw in data[:cut].splitlines():
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):      # not JSON (ValueError, which a bad byte or an oversized number also is), or nested too deep to parse: that line alone is skipped
            continue
        if isinstance(d, dict) and d.get("repo") and d.get("n"):
            rows.append(d)
    return rows, offset + cut
