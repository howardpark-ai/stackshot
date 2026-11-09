"""audit_overview.py — what the board's Audits page (GET /audits) and the side panel's Audit card say about the audits.

The audits run at three paces (every minute, every ten minutes, and the scheduled runs at each time of `[audit] at` plus the board's Audit now). This module lists them in groups and counts what
each group found in the last 24 hours, from the data the audits already write; it runs no audit and changes none.

    GROUPS                  the catalog: each group's name, a short description, whether its audits keep a findings log, and its audits as (name, pace, mode key)
    catalog()               the catalog with each audit's mode read from the configuration ("on", or "shadow", "off", ...)
    group_of(source, kind)  the group a findings-log row belongs to, None for a kind that no group lists
    day_rows(now)           the findings log's rows of the last 24 hours, read once
    card(now, rows)         the side panel card's rows: [{"name", "audits", "found"}] and the note under them (found is None for a group that keeps no log: the card draws a dash, never a zero)
    overview(now, runner, rows)   everything the page draws: paces, groups, the latest findings, the recent runs
  card, counts and overview take the day_rows a request has read already (`rows`), so one request reads the log once and its numbers agree.

Where the numbers come from:
  * the findings log, `<paths.state>/audit/findings-log.jsonl` (audit_run.log_findings): one row per appearance of a finding, with its time, the pass that made it (`source`), its kind and its item.
    It is kept while `[audit] pattern_review` is not "off", for 14 days. With the review off no log is written, so no group has a count: every found is None and the page says so.
  * the run records, `<paths.state>/audit/run-*.json` (audit.runs): when a run started and took, how many items it read, its findings and its model calls.
  * the runner's record (server._runner_status, passed in): when each tick last ran. Absent when the page is drawn without a server (a test), and the page then leaves "last" out.

A group whose audits keep no findings log (Fleet and services, Text and rules: they report to a machine or to CI, not to an item) has found None everywhere, whatever the log holds.
Standard library plus the repo's config and audit modules."""
from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from stackshot.audit import audit as _audit
from stackshot.core import config as _cfg

DAY = 86400.0
EVERY_MIN, EVERY_TEN, EACH_RUN = "every minute", "every 10 min", "each run"
RECENT_FINDINGS = 10         # the page lists this many of the newest findings
RECENT_RUNS = 8              # ... and this many runs

# (name, pace, mode key). A mode key names a switch in the configuration (see _mode); None is an audit that is always on.
GROUPS: tuple[dict[str, Any], ...] = (
    {"key": "silence", "name": "Silence", "desc": "an item or its mover not moving", "log": True, "audits": (
        ("answer tick", EVERY_MIN, None), ("hand-off tick", EVERY_MIN, None), ("stall tick", EVERY_MIN, None), ("silence pass", EVERY_TEN, None),
        ("the one ladder", "with the passes", "ladder"), ("unmoved digest", EACH_RUN, None), ("threshold message", EACH_RUN, None))},
    {"key": "filing", "name": "Filing", "desc": "an item's state is wrong", "log": True, "audits": (
        ("filing pass", EVERY_TEN, None), ("stuck-elsewhere", EVERY_TEN, None), ("arbitrary-hold", EVERY_TEN, None), ("mislabeled-state", EVERY_TEN, None),
        ("reads-as-wait", EVERY_TEN, None), ("wait-end", EVERY_TEN, "wait_end"), ("step-handover", EVERY_TEN, None), ("ask-options", EVERY_TEN, None), ("why-not-now (code)", EVERY_TEN, None),
        ("wrong-needs (model)", EACH_RUN, None), ("obsolete-wait (model)", EACH_RUN, None), ("why-not-now (model)", EACH_RUN, None))},
    {"key": "wording", "name": "Wording", "desc": "next steps and asks", "log": True, "audits": (
        ("ask-missing", EACH_RUN, None), *((f"next rules N{n}", EACH_RUN, None) for n in range(1, 8)),
        ("next-done (model)", EACH_RUN, None), ("ask no longer fits (model)", EACH_RUN, None), ("unneeded-escalation (model)", EACH_RUN, None), ("goal-unclear (model)", EACH_RUN, None))},
    {"key": "dates", "name": "Dates", "desc": "due dates and wake dates", "log": True, "audits": (
        ("dates pass", EVERY_TEN, None), ("For-you due-date look", EVERY_TEN, None), ("wake catch-up", EVERY_TEN, None))},
    {"key": "proof", "name": "Proof and patterns", "desc": "waits for proof, and repeat patterns", "log": True, "audits": (
        ("proof-waits stage", EACH_RUN, None), ("pattern review", "each run, last", "pattern"))},
    {"key": "pages", "name": "Pages and agents", "desc": "pages behind their items, agent lines", "log": True, "audits": (
        ("pilot fallback", EVERY_MIN, None), ("older-than-page (model)", EACH_RUN, None), ("pages stage", EACH_RUN, "pages"),
        ("page agent lines", EACH_RUN, None), ("project record check", EACH_RUN, None))},
    {"key": "fleet", "name": "Fleet and services", "desc": "machines and sessions", "log": False, "audits": (
        ("clients tick", EVERY_MIN, None), ("inbox flag", EVERY_MIN, None), ("hand-back tick", EVERY_MIN, None), ("roles sync", EVERY_MIN, None),
        ("orphan hand-over", EACH_RUN, "orphans"))},
    {"key": "text", "name": "Text and rules", "desc": "rulebook and tool text", "log": False, "audits": (
        ("rulebook scan", "after each run", None), ("retired-terms lint", "every PR", None), ("tool-text snapshot test", "every PR", None),
        ("tool-text touched check", "every PR", None), ("clean-text", "every PR", None))},
)

# the findings log's kinds (audit_checks.pattern_kind: the category, and for `next rules` and `board checks` the rule or kind after a colon) by group. `stale` is two audits' (the silence pass's and the dates pass's):
# the row's source, the pass that appended it, tells them apart.
# `wait-end` (a next line waits in words for something nothing tells the item has happened) and `event-missing` (the same rule found a wait that no event type reports) are the filing pass's waits, beside reads-as-wait.
_FILING = {"stuck-elsewhere", "board checks", "reads-as-wait", "wait-end", "event-missing", "step-handover", "ask-options", "why-not-now", "wrong-needs", "obsolete-wait"}
_WORDING = {"ask-missing", "next rules", "next-done", "goal-unclear", "unneeded-escalation"}
_BY_KIND = {**{k: "filing" for k in _FILING}, **{k: "wording" for k in _WORDING}, "proof-wait": "proof", "older-than-page": "pages"}
NOTE_UNLOGGED = "\u2013 keeps no findings log"      # the card's line under the list, and the page's reading of a dash
NOTE_LOG_OFF = "\u2013 the findings log is off"
SOURCES = {"run": "daily run", "silence": "silence", "filing": "filing", "dates": "dates"}     # the findings log's `source` as the page says it


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def group_of(source: str, kind: str) -> str | None:
    """The key of the group a findings-log row belongs to: by its kind, and for `stale` by the pass that appended it. None for a kind no group lists."""
    base = str(kind or "").split(":", 1)[0]
    if base == "stale":
        return "silence" if source == "silence" else "dates"
    return _BY_KIND.get(base)


def _mode(key: str | None) -> str:
    """An audit's mode as the configuration has it: "on" when it has no switch or its switch is on, else the switch's word ("shadow", "off", "report only")."""
    if not key:
        return "on"
    try:
        if key == "pattern":
            return _cfg.audit_pattern_review() if _cfg.audit_pattern_review() != "off" else "off"
        if key == "wait_end":
            return {"fix": "on", "ask": "ask only", "off": "off"}.get(_cfg.audit_wait_end(), "on")
        if key == "ladder":
            return "on" if _cfg.get("ladder", "enabled", default=False) is True else "off"
        if key == "orphans":
            return {"apply": "on", "report": "report only", "off": "off"}.get(_cfg.audit_orphan_handover(), "on")
        if key == "pages":
            from stackshot.router import page_debt as _pd
            return "off" if not _pd.enabled() else _pd.mode().replace("live", "on")
    except Exception:  # noqa: BLE001  — a switch that cannot be read leaves the audit listed as on, never an error on the page
        pass
    return "on"


def catalog() -> list[dict[str, Any]]:
    """GROUPS with each audit as {"name", "pace", "mode"}: the page's lists."""
    return [{"key": g["key"], "name": g["name"], "desc": g["desc"], "log": g["log"], "audits": [{"name": n, "pace": p, "mode": _mode(m)} for n, p, m in g["audits"]]} for g in GROUPS]


def log_kept() -> bool:
    """Whether the findings log is being written: `[audit] pattern_review` is not "off"."""
    return _cfg.audit_pattern_review() != "off"


def read_findings(since: float, until: float | None = None) -> list[dict[str, Any]]:
    """The findings log's rows with `since` < at (<= `until`), newest first; a line that does not parse, or that is not a finding's appearance, is skipped. [] when there is no log.
    The log is read as text with a damaged byte replaced (a line torn mid-character by a crash is then one more line that does not parse), and from the folder as it is: a missing folder is no log, and none is made."""
    try:
        text = (_cfg.state("audit") / _audit.FINDINGS_LOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for ln in text.split("\n"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        at = _num(r.get("at")) if isinstance(r, dict) else None
        if at is not None and at > since and (until is None or at <= until) and isinstance(r.get("id"), str) and r["id"] and isinstance(r.get("kind"), str):
            out.append({**r, "at": at})
    return sorted(out, key=lambda r: r["at"], reverse=True)


def day_rows(now: float) -> list[dict[str, Any]]:
    """The findings log's rows of the last 24 hours, newest first: [] while the log is not kept. One read of the log; a request that draws the card and the page passes this list on (`rows=`) so every number
    and row it shows comes from the same read (two reads can differ by a line that landed between them)."""
    return read_findings(now - DAY, now) if log_kept() else []


def counts(now: float, rows: list[dict[str, Any]] | None = None) -> dict[str, int | None]:
    """Findings in the last 24 hours by group key; None for a group that keeps no findings log (and for every group while the log is not kept). `rows`: the day_rows already read, else read here."""
    rows = day_rows(now) if rows is None else rows
    out: dict[str, int | None] = {}
    for g in GROUPS:
        out[g["key"]] = (0 if log_kept() else None) if g["log"] else None
    for r in rows:
        k = group_of(str(r.get("source") or ""), r["kind"])
        if k is not None and out.get(k) is not None:
            out[k] = int(out[k] or 0) + 1
    return out


def card(now: float, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The Audit card's shortlist: {"groups": [{"name", "audits", "found"}], "note"}. found is None where the group keeps no findings log, and the card draws a dash for it; note is the line under the
    list that says what the dash means ("" when no group has one). `rows`: the day_rows already read, else read here."""
    c = counts(now, rows)
    out = [{"name": g["name"], "audits": len(g["audits"]), "found": c[g["key"]]} for g in GROUPS]
    note = "" if all(r["found"] is not None for r in out) else (NOTE_UNLOGGED if log_kept() else NOTE_LOG_OFF)
    return {"groups": out, "note": note}


def _last_tick(runner: dict[str, Any] | None, names: tuple[str, ...]) -> float | None:
    """The newest `last_run` among the runner's ticks called `names`, None when the runner's record is absent or none of them has run."""
    best = None
    for t in (runner or {}).get("ticks") or []:
        if isinstance(t, dict) and t.get("name") in names:
            v = _num(t.get("last_run"))
            if v is not None and (best is None or v > best):
                best = v
    return best


def run_row(rec: dict[str, Any]) -> dict[str, Any]:
    """One run record as the page's table row: epoch started and finished (None when absent), the items read, the findings, the model calls made, and whether the run died or is unfinished."""
    f = rec.get("findings")
    calls = rec.get("calls") if isinstance(rec.get("calls"), dict) else {}
    made = calls.get("made")
    started, finished = _audit._epoch(rec.get("started")), _audit._epoch(rec.get("finished"))
    return {"started": started, "finished": finished, "items": rec.get("items_read") if isinstance(rec.get("items_read"), int) and not isinstance(rec.get("items_read"), bool) else None,
            "found": len(f) if isinstance(f, list) else (f if isinstance(f, int) and not isinstance(f, bool) else 0),
            "calls": made if isinstance(made, int) and not isinstance(made, bool) else None, "error": bool(rec.get("error"))}


def overview(now: float | None = None, runner: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything the Audits page draws:
    enabled, times (the scheduled times of day), next (epoch or None), running_since (epoch or None), groups (catalog() with found per group), total (audits), found (findings in 24 h, None while no log is kept),
    recent (the newest findings: {at, id, kind, source, agent, detail}), runs (run_row for the newest runs), ten_last (when the ten-minute set last ran, None when unknown), log (whether the findings log is kept).
    The findings log is read once (`rows`: the day_rows already read, else read here): the counts, the total and the rows come from the same list."""
    now = time.time() if now is None else now
    rows = day_rows(now) if rows is None else rows
    enabled = _cfg.audit_enabled()
    there = _cfg.state("audit").is_dir()      # the page only reads: no folder, no records, and nothing is made (the log is read without making the folder too)
    cat, c = catalog(), counts(now, rows)
    for g in cat:
        g["found"] = c[g["key"]]
    runs = _audit.runs(limit=RECENT_RUNS) if there else []
    run = _audit.running(now) if there else None
    kept = log_kept()
    found = len(rows) if kept else None
    return {"enabled": enabled, "times": list(_cfg.audit_at()), "next": _audit.next_run(now), "running_since": _audit._epoch(run.get("started")) if run else None,
            "groups": cat, "total": sum(len(g["audits"]) for g in cat), "found": found, "log": kept,
            "recent": [{"at": r["at"], "id": r["id"], "kind": r["kind"], "source": str(r.get("source") or ""), "agent": str(r.get("agent") or "-"), "detail": str(r.get("detail") or "")}
                       for r in rows[:RECENT_FINDINGS]],
            "runs": [run_row(r) for r in runs], "ten_last": _last_tick(runner, ("filing_tick", "dates_tick", "silence_tick"))}


SHOWN = re.compile(r"(.+)#([0-9]+)")        # [0-9], not \d: a digit of another script is no id; matched whole, so a trailing newline is no id either
TMP_PREFIX = re.compile(r"board-tmp-[a-z0-9]+(?:-[a-z0-9]+)*")      # lowercase words joined by single dashes: no trailing or doubled dash


def item_path(shown: str) -> str | None:
    """The part of an item page's address (`/items/<part>`) for an id as the findings log writes it: `board#<n>` is `<n>`, a temporary id `<prefix>#<n>` is `<prefix>-<n>`; None for any other shape."""
    m = SHOWN.fullmatch(shown or "")
    if not m:
        return None
    if m.group(1) == "board":
        return m.group(2)
    return f"{m.group(1)}-{m.group(2)}" if TMP_PREFIX.fullmatch(m.group(1)) else None
