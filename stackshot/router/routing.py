"""routing.py — the routing log: one line for every notice stackshot recorded for a project, and how it was ruled (by the router, whose
rulings carry its name; the `route` tool overrules one).

Part of the pilot, now the router's for every project.
anchor-hub records each anchor notice it delivers; the server records an agent's board write and a message addressed to a project.
The router answers each line with a ruling: passed (to an agent) · merged (into a digest) · held · dropped. A line with no ruling is
pending — the router's backlog, and the sign that it is behind. A line recorded with `pilot` false (a direct anchor, a log-only one)
is only a count of what came in.

Store: <state>/routing/<project key, "/" → "__">.jsonl, append-only. A notice line carries an id; a ruling is a later line
naming that id (the last one wins), so the hub and the server can both append without rewriting. Stdlib only.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core.lines import newline_lines

DIR: Path = _cfg.state("routing")
RULINGS = ("passed", "merged", "held", "dropped")
KEEP_DAYS = 30          # what a read returns at most; the files keep everything
_NID = re.compile(r"[0-9a-f]{6}")      # a notice id: record() mints secrets.token_hex(3)
AUTO_RULER = "stackshot (auto)"     # who rules a log-only notice at once (the turn rule): the server's and anchor-hub's own name


def _file(project: str) -> Path:
    return DIR / (str(project).strip("/").replace("/", "__") + ".jsonl")


def _append(project: str, line: dict[str, Any]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(_file(project), "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def record(project: str, *, kind: str, to: str, label: str = "", who: str = "", text: str = "", url: str = "", target: str = "",
           pilot: bool = False, anchor: str = "", ts: float | None = None, reason: str = "", log_only: bool = False, batch: str = "",
           live: bool = False, words: str = "", handback: bool = False, head: str = "", author: str = "", etype: str = "", hold: str = "") -> str:
    """One delivered notice → its id. kind: anchor · board · message. `to` = the session it went to; `target` = the agent it
    is for, or "project-wide" (pilot projects); text = the one-line gist. A line logged without delivery (a log-only direct
    anchor) has `to` empty and says why in `reason`, which the routing page shows in its reason column. `log_only` marks such a line explicitly, `"log_only": true`, so a count of the turns notices
    cost can leave it out whatever its `to` reads; a green release.sh result is one, ruled merged by `stackshot (auto)` at once, and
    so is a routine event on the fleet's own PR (record_auto).
    `batch` (the turn rule's fourth build): the id shared by the notices that went out together in one
    message (page debts moved to one keeper in one tick, items woken for one session in one pass),
    so a count of the turns notices cost counts that message once; a notice delivered alone carries none.
    `live` (router_live.py): the notice was NOT delivered to the name the project's notices are addressed to, `to` is empty, and the router
    rules it and delivers it to the agent it fits; `"live": true` is the router's work list.
    `words` (a close with the owner's own words on the item, telling.tell_close_owner): what shows they are there ("a said entry",
    "quoted in the text"); `"words": …` is the mark router.py's close-words rule reads.
    `handback` (an item handed back to its front agent owner alone, telling.tell_handback): `"handback": true` is the mark router.py's
    hand-back rule reads.
    `head`, `author` (a GitHub pull request's anchor notice, anchor-hub): the PR's head branch and its author's login. The router's
    anchor-builder rule passes a notice on a branch prefixed with a background agent's name to that agent, not to the item's front keeper.
    `etype` (anchor-hub's event type at its source, `ci_failed`, `ci_passed`, `ci_activity`, `comment`, several joined with "+"): the router's
    anchor-ci rule passes a CI notice to the project's builder; a notice recorded without it is read by its `who` ("CI").
    `hold` (held.KINDS): the sender's word that this notice asks nothing of a background agent (a page-owed notice, a message marked fyi).
    The router, when it passes the notice to a background agent, holds it for that agent's next turn instead (router_live._hold_kind); a front agent is unaffected."""
    nid = secrets.token_hex(3)
    line = {"id": nid, "ts": float(ts if ts is not None else time.time()), "kind": kind, "to": to, "label": label, "who": who,
            "text": " ".join(str(text).split())[:300], "url": url, "target": target, "pilot": bool(pilot), "anchor": anchor}
    if reason: line["reason"] = " ".join(str(reason).split())[:300]
    if log_only: line["log_only"] = True
    if batch: line["batch"] = str(batch)
    if live: line["live"] = True
    if words: line["words"] = " ".join(str(words).split())[:60]
    if handback: line["handback"] = True
    if head: line["head"] = str(head)[:200]
    if author: line["author"] = str(author)[:100]
    if etype: line["etype"] = str(etype)[:80]
    if hold: line["hold"] = str(hold)[:20]
    _append(project, line)
    return nid


def record_auto(project: str, ruling: str, why: str, **kw: Any) -> str:
    """A notice logged and not delivered, ruled at once by AUTO_RULER (the turn rule's third build: a routine
    event on the fleet's own PR, from anchor-hub): one `record` line with no recipient, `log_only` and `reason`, then its ruling
    line, appended to the same project file without the cross-project lookup rule() makes. → the notice id. `kw` = record()'s
    other fields (kind, label, who, text, url, target, pilot, anchor, ts)."""
    if ruling not in RULINGS:
        raise ValueError(f"ruling must be one of {' | '.join(RULINGS)}")
    nid = record(project, to="", reason=why, log_only=True, **kw)
    _append(project, {"id": nid, "ruling": ruling, "to": "", "reason": " ".join(str(why).split())[:300], "by": AUTO_RULER, "ts": time.time()})
    return nid


def projects() -> list[str]:
    return sorted(p.name[:-6].replace("__", "/") for p in DIR.glob("*.jsonl")) if DIR.is_dir() else []


def _fold(lines: list[str]) -> dict[str, dict[str, Any]]:
    """Log lines (oldest first) → {id: notice}, each with its latest ruling merged in and its reminders (read's merge, in one place)."""
    notices: dict[str, dict[str, Any]] = {}
    for ln in lines:
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if "ruling" in d and "kind" not in d:
            n = notices.get(str(d.get("id")))
            if n is not None:
                n.update({"ruling": d["ruling"], "ruled_to": d.get("to", ""), "reason": d.get("reason", ""), "ruled_at": d.get("ts", 0), "ruled_by": d.get("by", "")})
        elif "reminder" in d and "kind" not in d:              # a reminder line of the earlier form (sessions were reminded): stage → when; no new one is written
            n = notices.get(str(d.get("id")))
            if n is not None:
                n.setdefault("reminders", {})[str(d["reminder"])] = float(d.get("ts", 0))
                cnt = n.setdefault("reminder_counts", {}); cnt[str(d["reminder"])] = cnt.get(str(d["reminder"]), 0) + 1
        elif d.get("id"):
            notices[str(d["id"])] = d
    return notices


def read(project: str, since: float = 0.0) -> list[dict[str, Any]]:
    """The project's notices from `since` (epoch), oldest first, each with its latest ruling merged in (ruling, ruled_to,
    reason, ruled_at, ruled_by) or without those keys when none was given, and the reminders sent about it: `reminders`
    (stage → when the latest went out) and `reminder_counts` (stage → how many went out)."""
    since = max(float(since), time.time() - KEEP_DAYS * 86400)
    try:
        lines = newline_lines(open(_file(project), encoding="utf-8").read())
    except OSError:
        return []
    return [n for n in _fold(lines).values() if float(n.get("ts", 0)) >= since]


def lines_with(data: bytes, needle: str) -> list[str]:
    """The lines of a file's bytes that contain `needle`, found by byte search and cut at their newlines, decoded one by one: a file is
    neither decoded nor split as a whole (the log is mostly lines that are not the one looked for)."""
    out: list[str] = []
    nb = needle.encode("utf-8")
    pos = data.find(nb)
    while pos != -1:
        end = data.find(b"\n", pos)
        end = len(data) if end < 0 else end
        out.append(data[data.rfind(b"\n", 0, pos) + 1:end].decode("utf-8", "replace"))
        pos = data.find(nb, end)
    return out


def lookup(nid: str, hint: str = "") -> tuple[str, dict[str, Any]] | None:
    """(project, notice with its latest ruling merged in) for a notice id, whichever project it belongs to and however old it is
    (read keeps KEEP_DAYS; this does not). Each project's file is searched as bytes and only the lines that carry the id are decoded and parsed, so a
    lookup across all projects costs a substring search, not a parse of every line. `hint` = the project key to try first (the live
    log knows it). None for an id that is not six hex characters and for one no file holds."""
    nid = str(nid).strip().lower()
    if not _NID.fullmatch(nid):
        return None
    needle = f'"id": "{nid}"'                    # json.dumps' own form of the first key of every line the log appends
    for p in ([hint] if hint else []) + [x for x in projects() if x != hint]:
        try:
            data = _file(p).read_bytes()
        except OSError:
            continue
        hit = _fold(lines_with(data, needle)).get(nid)
        if hit is not None:
            return p, hit
    return None


def find(nid: str) -> tuple[str, dict[str, Any]] | None:
    """(project, notice) for a notice id, whichever project it belongs to (within what read returns: KEEP_DAYS)."""
    hit = lookup(nid)
    return hit if hit is not None and float(hit[1].get("ts", 0)) >= time.time() - KEEP_DAYS * 86400 else None


def rule(nid: str, ruling: str, to: str = "", reason: str = "", by: str = "") -> tuple[str, dict[str, Any]]:
    """Record the ruling on a notice (again to overrule an earlier one). → (project, the notice as it now reads)."""
    ruling = str(ruling).strip().lower()
    if ruling not in RULINGS:
        raise ValueError(f"ruling must be one of {' | '.join(RULINGS)}")
    hit = find(nid)
    if hit is None:
        raise KeyError(nid)
    project, _n = hit
    _append(project, {"id": str(nid).strip().lower(), "ruling": ruling, "to": str(to).strip(), "reason": " ".join(str(reason).split())[:300], "by": str(by).strip(), "ts": time.time()})
    return project, next(n for n in read(project) if n["id"] == str(nid).strip().lower())


def counts(keys: list[str], hours: float = 24.0, now: float | None = None, wait: float = 3600.0) -> dict[str, int]:
    """What came in for these page keys in the last `hours`, and how it was ruled: {in, passed, merged, held, dropped, pending,
    waiting, escalated}. `pending` counts pilot notices without a ruling, whatever their age within the log's reach: an old one is still
    owed. `waiting` is the part of them older than `wait` seconds: what the board flags. `escalated` is the
    part the project's -main agent had been told about (old log lines only: reminders["agent"]; nothing sets it any more)."""
    now = time.time() if now is None else now
    out = {"in": 0, "pending": 0, "waiting": 0, "escalated": 0, **{r: 0 for r in RULINGS}}
    for k in keys:
        for n in read(k):
            recent = float(n.get("ts", 0)) >= now - hours * 3600
            if recent:
                out["in"] += 1
                if n.get("ruling") in RULINGS:
                    out[n["ruling"]] += 1
            if n.get("pilot") and not n.get("ruling"):
                out["pending"] += 1
                if float(n.get("ts", 0)) <= now - wait:
                    out["waiting"] += 1
                if "agent" in (n.get("reminders") or {}):
                    out["escalated"] += 1
    return out


def stamp() -> float:
    """The newest change in the log (for the server's republish watcher)."""
    return max((p.stat().st_mtime for p in DIR.glob("*.jsonl")), default=0.0) if DIR.is_dir() else 0.0
