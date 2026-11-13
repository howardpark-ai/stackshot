"""subagent_tie.py: which running subagent of a mover is at work on WHICH item: the hourly audit's proof that "a subagent is running on it" (audit/hourly.py).

A step status in progress (silence.subagent_running) is something the mover wrote: a claim, and one mover can carry it on several items while one subagent runs. The pane being busy is
the same sort of claim about the mover, not about an item. The audit therefore asks the subagent itself, from the transcript Claude Code keeps on the server's box:

  <root>/<working-directory folder>/<session uuid>/subagents/agent-<id>.meta.json    {"description": "...", "finished": true once it ended, ...}
  <root>/<working-directory folder>/<session uuid>/subagents/agent-<id>.jsonl        its transcript, the first line the brief the mover gave it

`running(session, roots, now)` lists a session's subagents that are running: no `finished` flag and the transcript written within `RUNNING_S`. A subagent whose pane was recycled or killed leaves
neither a flag nor a later write, so it stops counting after that window (the same 90 minutes the step status is trusted for: silence.SUBAGENT_S). The caller (server `_mover_subagents`) asks
only for a pane that is busy now, since a subagent keeps its pane in a turn.

`tied(subagents, shown, keys)` says whether one of them is on an item: its description or its brief names the item (its shown id, `board#N`, whole: `board#12` is not `board#123`) or a pull request
anchored to the item (`keys`, "owner/repo#n", by its URL or by `PR n` / `#n`, as merge_tie names a pull request for an item that speaks of its repository). A subagent that names neither is on no item the
audit can tell, and an item nothing is tied to reads idle (and part F, audit/hand_idle.py, hands it on). A session whose transcript this box does not hold (another machine, a cloud session) shows
no subagent: nothing can be verified, so nothing is claimed.

Stdlib plus the repo's modules; reads files only."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from stackshot.model import merge_tie as _mt
from stackshot.model import said as _said

RUNNING_S = 90 * 60.0          # a subagent with no `finished` flag counts as running while its transcript was written within this long
BRIEF_BYTES = 256 * 1024       # of the first line of its transcript (the brief) at most this many bytes are read
BRIEF_CHARS = 20000            # and at most this many characters of the brief are kept
SKEW_S = 300.0                 # a transcript dated this far ahead of the clock is a skew of clocks, still running


def _brief(path: Path) -> str:
    """The text of the first message of a subagent's transcript (the brief its mover gave it), "" when it cannot be read: a string, or the text blocks of a list."""
    try:
        with open(path, "rb") as f:
            line = f.readline(BRIEF_BYTES)
        msg = (json.loads(line).get("message") or {}).get("content")
    except (OSError, ValueError, AttributeError):
        return ""
    if isinstance(msg, list):
        msg = "\n".join(str(b.get("text") or "") for b in msg if isinstance(b, dict))
    return msg[:BRIEF_CHARS] if isinstance(msg, str) else ""


def running(session: str, roots: Any, now: float) -> list[dict[str, Any]]:
    """The running subagents of the session (a transcript uuid) as this box holds them: [{"id", "text", "at"}], `text` the description and the brief, `at` the transcript's last write. [] when the session
    has no transcript here or no subagent running. A meta or a transcript that cannot be read is left out."""
    path = _said.find_transcript(session, roots)
    if path is None:
        return []
    out: list[dict[str, Any]] = []
    try:
        metas = sorted((path.parent / path.stem / "subagents").glob("agent-*.meta.json"))
    except OSError:
        return []
    for mp in metas:
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
            tp = mp.with_name(mp.name[: -len(".meta.json")] + ".jsonl")
            at = tp.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("finished") is True or not (-SKEW_S <= now - at <= RUNNING_S):
            continue
        out.append({"id": mp.name[len("agent-"): -len(".meta.json")], "text": f"{meta.get('description') or ''}\n{_brief(tp)}", "at": at})
    return out


def names_item(text: str, shown: str, keys: Iterable[str] = ()) -> bool:
    """Does `text` name the item (its shown id, whole and in any case) or a pull request anchored to it (`keys`, "owner/repo#n")? A pull request is named by its URL, or by `PR n` / `#n` (the item
    speaks of that repository: a pull request of it is anchored to the item)."""
    t = str(text or "")
    if shown and re.search(r"(?<![\w#])" + re.escape(shown) + r"(?![\w])", t, re.I):
        return True
    return any(_mt.names(t, k.lower(), [_mt.repo_of(k.lower())]) for k in keys if k)


def tied(subagents: Iterable[dict[str, Any]], shown: str, keys: Iterable[str] = ()) -> bool:
    """Is one of the running `subagents` (from `running`) at work on the item: its description or brief names the item or a pull request anchored to it."""
    keys = [k for k in keys if k]
    return any(names_item(str(s.get("text") or ""), shown, keys) for s in subagents or ())
