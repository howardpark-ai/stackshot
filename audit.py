#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.uv]
# exclude-newer = "2026-10-03T04:00:00Z"
# ///
"""audit.py — the server side of the daily board audit (a script; the audit agent is the alternative mode).

Two modes, `[audit] mode`. "script" (the default): the audit is a script, audit_run.py, in code where a check reads only item fields and one `claude -p` call per suspect item where it needs
judgment; it writes the run record and sends the findings. "agent": the audit is done by a Claude Code session, the audit agent ([audit] agent), which reads the board, writes the record
and reports; this module only cues it. Switching `mode` back to "agent" is the rollback. In both modes the record is read here:

    <paths.state>/audit/run-<YYYY-MM-DD>-<HHMMSS>.json   one per run, the start time in the [instance] timezone (a script run; a second run the same day, as the twice-a-day timer makes, keeps the first one's record), or
    <paths.state>/audit/run-<YYYY-MM-DD>.json            the agent's plain name; readers take the newest of a day by its `started`. Written by the run (the agent or audit_run.py):
        {"started": epoch | ISO-8601, "finished": epoch | ISO-8601 | null while in progress, "items_read": int,
         "findings": [{"id", "project", "owner", "category"}, …], "by_session": {name: count}, "by_category": {category: count}}
        (a script run adds detail and source to each finding, and idle_pass, stuck, judged, calls and messages beside them; a run that died has `error` and is finished)
    <paths.state>/audit/cues.jsonl              one line per cue, whatever its outcome, and one per script run that ends (finished or died): {"ts", "reason", "code", "text"}
    <paths.state>/audit/cue.lock                the exclusive lock a cue (and `audit.py run`) takes around the check "is a run in progress" and the writing of the running record
    <paths.state>/audit/run.log                 the output of the detached run the button starts

A cue comes from the timer (stackshot-audit.timer → `audit.py cue scheduled`, every day at each time of [audit] at) or from the board's "Audit now" button (POST /audit/now → cue("button")). In script
mode the timer's `audit.py cue scheduled` runs the audit in its own process, and the button's cue writes the running record and starts `audit.py run` as a detached process (the call
returns at once); in agent mode a cue is one line pushed to the agent through push.py, the same delivery the wake pass uses. Either way: 202 started or delivered · 409 a run is in
progress · 404 [audit] enabled is false · 503 the run could not start (agent mode: the agent is not live; push.py's own answer is in the text). A record whose `finished` is null and
whose `started` is two hours old or more is a crashed run, not a running one: it does not hold a new cue back.

    audit.py cue <reason>     start the audit now (the mode decides how); prints the outcome, exit 0 on 202, 1 otherwise
    audit.py run [--dry-run]  one script-mode run now (audit_run.py), refused (exit 1) while a run is in progress, when [audit] enabled is false or when the mode is "agent"; --dry-run lists
                              the field findings and the suspects, makes no model call, sends nothing, writes no record, and is never refused
    audit.py status           print GET /audit/status's JSON
    audit.py scan [--dry-run] the rulebook scan (tools/rulebook_scan.py): the instruction files sessions read are checked for
                              stackshot tools, parameters, sala verbs and flags and retired terms that no longer exist, and each file's keeper gets
                              one note (a message through client.py, as a script's message); [rulebook_scan] enabled gates it, --dry-run only prints.
                              The timer's unit runs tools/rulebook_scan.py just after the cue (ExecStartPost: after the run and its page checks; its failure never fails the unit).
                              No model, no tokens.
    audit.py refusals [--dry-run] [--force] [--week DATE]  the weekly count of refused board writes (tools/refusal_report.py): the last full week, Monday to Sunday, sent once to [refusal_report] to
                              (default [audit] summary_to) as a message that asks nothing; [refusal_report] enabled gates it, --dry-run only prints. The timer's unit runs it after the run. No model, no tokens.
    audit.py next-check [--line|--json]   the open items that break the Next rules N1 to N7 (tools/next_report.py): read only, the
                              audit agent lists each as a finding of the category `next rules`. Closed items are left as they are. No model, no tokens.
    audit.py board-check [--line|--json]  the open items that are held for no concrete reason or carry the wrong state (tools/board_report.py):
                              read only, the audit agent lists each as a finding of the category `board checks`, naming the item's mover. No model, no tokens.
    audit.py page-agents [--line|--json]  the lines of a project page's `agents:` map, `agent:` and `display-name:` that name a session sala no longer knows
                              (tools/page_agent_report.py): read only, nothing is sent. The daily run (audit_run.py, script mode) sends each page's -main agent one message
                              listing its page's leftovers. Nothing is flagged when sala's session list cannot be read or is empty. No model, no tokens.
    audit.py registry [--line|--json]  what is wrong with the project record and the pages it points at, each problem with the command that fixes it (tools/registry_report.py): a page with no project, a
                              project whose page is gone, page lines that differ from the record, an agent on no live session, items whose project id or key no project has, two live projects on one page.
                              Read only, nothing is sent. The daily run puts the findings on its record, and sends each project's -main agent one message a day only with `[registry_audit] send = true` (off by default). Not checked
                              when the record has no projects. No model, no tokens.
    audit.py orphans [--apply]  the open items whose mover is a session that is gone (a project's last agent retired, say) and the closest live agent each would go to (successor.py): a dry run, nothing
                              written and nobody told; --apply hands them over, as the daily run's first stage does ([audit] orphan_handover: "report" the default, which lists and moves nothing even with --apply; "apply" to hand over; "off"). An item an owner moves is never
                              listed, and one with no live agent to take it stays and is listed as such. Needs the server reached: it makes the check and the writes. No model, no tokens.
Stdlib only: imported by the server, run by the timer's unit."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as _cfg  # noqa: E402
import interp as _interp  # noqa: E402  — a missing interpreter (its uv environment deleted) never stops a delivery

RUNNING_MAX = 2 * 3600            # s: an unfinished record older than this is a crashed run
PUSH = [sys.executable, str(HERE / "push.py")]


def state_dir() -> Path:
    """<paths.state>/audit, made on first use."""
    d = _cfg.state("audit")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _when(ts: float) -> str:
    """An epoch as the server writes a time elsewhere (the message envelope): 2099-03-05 05:00 UTC (the zone's own abbreviation)."""
    return dt.datetime.fromtimestamp(float(ts), _cfg.tz()).strftime("%Y-%m-%d %H:%M %Z")


def _record_date(stem: str) -> str | None:
    """The day a record file's stem names: `run-2099-03-05` (the agent's) or `run-2099-03-05-050000` (a script run's); None for any other name."""
    if not stem.startswith("run-"):
        return None
    rest = stem[len("run-"):]
    date, tail = rest[:10], rest[10:]
    if tail and not (len(tail) == 7 and tail[0] == "-" and tail[1:].isdigit()):
        return None
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return None
    return date


def runs(limit: int | None = None) -> list[dict[str, Any]]:
    """The run records, newest first (by the day in the file name, then by `started` within a day, so a second run the same day reads as the newer), each with its `date`; a file that does not parse
    as a JSON object is skipped."""
    days: dict[str, list[Path]] = {}
    for p in state_dir().glob("run-*.json"):
        d = _record_date(p.stem)
        if d is not None:
            days.setdefault(d, []).append(p)
    out: list[dict[str, Any]] = []
    for date in sorted(days, reverse=True):
        day = []
        for p in days[date]:
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(rec, dict):
                day.append((_epoch(rec.get("started")) or 0.0, p.name, {**rec, "date": date}))
        out += [r for _s, _n, r in sorted(day, key=lambda x: (x[0], x[1]), reverse=True)]
        if limit is not None and len(out) >= limit:
            break
    return out[:limit] if limit is not None else out


def _epoch(v: Any) -> float | None:
    """A run record's time as epoch seconds, or None when it is absent or cannot be read. The agent writes a number or an ISO-8601
    string (`2099-03-28T05:10+00:00`, a trailing `Z` too; a string with no offset is read in the [instance] timezone, the zone of the
    record's date); a bool, a non-finite number, an empty or unreadable string is None, never an error."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip()
        try:
            t = float(s)
        except ValueError:
            try:
                d = dt.datetime.fromisoformat(s)
                t = (d if d.tzinfo else d.replace(tzinfo=_cfg.tz())).timestamp()
            except (ValueError, OverflowError, OSError):
                return None
    else:
        try:
            t = float(v)
        except (TypeError, ValueError, OverflowError):
            return None
    return t if math.isfinite(t) else None


def running(now: float | None = None) -> dict[str, Any] | None:
    """The run in progress: a record with `finished` null whose `started` is less than two hours before `now`; else None."""
    now = time.time() if now is None else now
    for rec in runs():
        started = _epoch(rec.get("started"))
        if rec.get("finished") is None and started is not None and 0 <= now - started < RUNNING_MAX:
            return rec
    return None


def last() -> dict[str, Any] | None:
    """The newest run record (finished, running or crashed), or None."""
    r = runs(limit=1)
    return r[0] if r else None


def next_run(now: float | None = None) -> float | None:
    """The epoch of the next scheduled run ([audit] at, each time of it in the [instance] timezone, as the timer has it: the soonest of today's
    times still ahead, else the first of tomorrow's), or None when the audit is not enabled. A run at exactly `now` counts as gone."""
    if not _cfg.audit_enabled():
        return None
    z = _cfg.tz()
    t = dt.datetime.fromtimestamp(time.time() if now is None else now, z)
    best: float | None = None
    for day in (t.date(), t.date() + dt.timedelta(days=1)):
        for hhmm in _cfg.audit_at():
            hh, mm = (int(x) for x in hhmm.split(":"))
            at = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=z)
            if at > t and (best is None or at.timestamp() < best):
                best = at.timestamp()
    return best


def status(now: float | None = None) -> dict[str, Any]:
    """GET /audit/status: whether the audit is on, its agent, whether a run is in progress and since when, the last run in
    brief (its findings as a count) and the next scheduled run. Every time in it (`running_since`, the last run's `started` and
    `finished`, `next`) is epoch seconds or null, whether the record holds a number or an ISO-8601 string."""
    run = running(now)
    rec = last()
    brief = None
    if rec is not None:
        f = rec.get("findings")
        brief = {"date": rec.get("date"), "started": _epoch(rec.get("started")), "finished": _epoch(rec.get("finished")),
                 "items_read": rec.get("items_read"),
                 "findings": len(f) if isinstance(f, list) else (f if isinstance(f, int) and not isinstance(f, bool) else 0),
                 "by_category": rec.get("by_category") or {}, "by_session": rec.get("by_session") or {}}
    return {"enabled": _cfg.audit_enabled(), "agent": _cfg.audit_agent(), "running": run is not None,
            "running_since": _epoch(run.get("started")) if run else None, "last": brief, "next": next_run(now)}


def _push(agent: str, text: str) -> tuple[bool, str]:
    """One line to the agent through push.py (the message source, as the wake pass sends). → (delivered, push.py's answer:
    its last stdout line, and its last stderr line when there is one)."""
    try:
        r = subprocess.run([*_interp.resilient(PUSH), "--from", "stackshot audit", agent, text], capture_output=True, text=True, timeout=110,
                           env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
        out = (r.stdout.strip().splitlines() or [""])[-1]
        err = (r.stderr.strip().splitlines() or [""])[-1]
    except subprocess.TimeoutExpired:
        return False, "push.py did not return within 110 s"
    except Exception as e:  # noqa: BLE001
        return False, f"push.py failed: {e}"
    return out.startswith("delivered"), (out or "no result") + (f" — {err}" if err else "")


def _log(reason: str, code: int, text: str, now: float) -> None:
    try:
        with open(state_dir() / "cues.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now, "reason": reason, "code": code, "text": text}, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"audit: cue log not written: {e}", file=sys.stderr, flush=True)


def _spawn_run(started: float) -> None:
    """Start `audit.py run --started <epoch>` as a process of its own (a new session: it outlives the server's request and a restart of the server). The server's button path; the child checks
    that the running record `started` names is there before it does anything. Its output goes to <audit state>/run.log, so a crash that happens before the run can write its own record is not silent."""
    with open(state_dir() / "run.log", "a", encoding="utf-8") as log:
        log.write(f"--- {_when(started)}: audit.py run --started {float(started)!r}\n")
        log.flush()
        subprocess.Popen([*_interp.resilient([sys.executable, str(HERE / "audit.py")]), "run", "--started", repr(float(started))],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(HERE))


@contextlib.contextmanager
def _cue_lock():
    """An exclusive flock on <audit state>/cue.lock, held while a cue checks that no run is in progress and writes the running record, so two cues at once cannot both pass the check. Held for
    milliseconds, never across a run. A lock file that cannot be opened lets the cue go on without it (a note on stderr)."""
    try:
        f = open(state_dir() / "cue.lock", "a+")
    except OSError as e:
        print(f"audit: cue lock not taken: {e}", file=sys.stderr, flush=True)
        yield
        return
    with f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def claim(now: float) -> tuple[int, str]:
    """Under the lock: the guards a run has to pass and, in script mode, the running record. -> (202, "") the running record for `now` is written and the caller is to run the audit · (409, text) a run
    is in progress · (404, text) the audit is not enabled · (0, "") the mode is "agent": no record, the caller cues the agent. Used by `cue` and by `audit.py run`."""
    with _cue_lock():
        run = running(now)
        if run is not None:
            return 409, f"an audit is running since {_when(_epoch(run.get('started')))}"
        if not _cfg.audit_enabled():
            return 404, "the audit is not enabled on this instance ([audit] enabled)"
        if _cfg.audit_mode() != "script":
            return 0, ""
        import audit_run as _run  # noqa: PLC0415 — only a script-mode run needs it
        _run.start_record(now)
        return 202, ""


def _cue_script(now: float, inline: bool) -> tuple[int, str]:
    """Script mode, the running record written by `claim`: run the audit now. `inline` (the command line, the timer's unit): in this process; -> 202 and the run's one-line summary when it ends. Not inline
    (the server's button): start the run as a detached process and answer at once. A run that dies has finished its own record (with `error`), so the next cue is not held back."""
    import audit_run as _run  # noqa: PLC0415
    if inline:
        try:
            rec = _run.run(now=now, started=now)
        except Exception as e:  # noqa: BLE001 — the run has written its record as finished with the error; the cue log says why
            return 503, f"the audit run failed: {type(e).__name__}: {e}"
        return 202, f"audit run: {rec['items_read']} open items · {len(rec['findings'])} findings · {rec['calls']['made']} model call(s)"
    try:
        _spawn_run(now)
    except Exception as e:  # noqa: BLE001
        try:
            _run._record_path(now).unlink()
        except OSError:
            pass
        return 503, f"the audit run could not be started: {e}"
    return 202, "audit run started"


def cue(reason: str, now: float | None = None, inline: bool = False) -> tuple[int, str]:
    """The one entry point for the timer and the button: start the audit now. `[audit] mode` decides how: "script" runs audit_run.py (in this process when `inline`, else as a detached process);
    "agent" cues the audit agent with one line. -> (HTTP code, text): 202 started or delivered · 409 a run is in progress · 404 the audit is not enabled · 503 it could not start (agent mode: the
    agent is not live). The check and the running record are written under one exclusive lock (`claim`). Every cue is logged to cues.jsonl, whatever its outcome."""
    now = time.time() if now is None else now
    reason = str(reason or "").strip() or "unspecified"
    code, text = claim(now)
    if code == 202:
        code, text = _cue_script(now, inline)
    elif code == 0:
        agent = _cfg.audit_agent()
        line = (f"[stackshot] Audit now ({reason}, {_when(now)}): run the audit as your brief says, write the run record, "
                "report as usual.")
        ok, said = _push(agent, line)
        code, text = (202, f"audit cued to {agent}") if ok else (503, f"the audit agent {agent} is not running: {said}")
    _log(reason, code, text, now)
    return code, text


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "cue":
        code, text = cue(argv[1], inline=True)
        print(text)
        return 0 if code == 202 else 1
    if argv == ["status"]:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if argv[:1] == ["run"]:
        import audit_run  # noqa: PLC0415 — only the run verb needs it
        return audit_run.main(argv[1:])
    if argv[:1] == ["scan"]:
        sys.path.insert(0, str(HERE / "tools"))
        import rulebook_scan  # noqa: PLC0415 — only the scan verb needs it
        return rulebook_scan.main(["run", *argv[1:]])
    if argv[:1] == ["refusals"]:
        sys.path.insert(0, str(HERE / "tools"))
        import refusal_report  # noqa: PLC0415 — only the refusals verb needs it
        return refusal_report.main(["run", *argv[1:]])
    if argv[:1] == ["next-check"]:
        sys.path.insert(0, str(HERE / "tools"))
        import next_report  # noqa: PLC0415 — only the next-check verb needs it
        return next_report.main(argv[1:])
    if argv[:1] == ["board-check"]:
        sys.path.insert(0, str(HERE / "tools"))
        import board_report  # noqa: PLC0415 — only the board-check verb needs it
        return board_report.main(argv[1:])
    if argv[:1] == ["page-agents"]:
        sys.path.insert(0, str(HERE / "tools"))
        import page_agent_report  # noqa: PLC0415 — only the page-agents verb needs it
        return page_agent_report.main(argv[1:])
    if argv[:1] == ["registry"]:
        sys.path.insert(0, str(HERE / "tools"))
        import registry_report  # noqa: PLC0415 — only the registry verb needs it
        return registry_report.main(argv[1:])
    if argv[:1] == ["orphans"] and set(argv[1:]) <= {"--apply"}:
        return orphans("--apply" in argv)
    print("usage: audit.py cue <reason> | run [--dry-run] | status | scan [--dry-run] | refusals [--dry-run] [--force] [--week DATE] | next-check [--line|--json] | board-check [--line|--json] | page-agents [--line|--json] | registry [--line|--json] | orphans [--apply]", file=sys.stderr)
    return 2


def orphans(apply: bool) -> int:
    """By hand: the open items whose mover is a session that is gone, and where each would go (a dry run, nothing written), or with --apply the hand-over itself (the daily run makes it too). The server makes the
    check, so this needs the server reached → exit 0, 1 refused or not reached."""
    import client as _client  # noqa: PLC0415 — only this verb needs it
    status, d = _client.orphan_handover(apply)
    if status != 200:
        print(f"audit: orphan hand-over not run [{status}] {str(d.get('error') or d)[:300]}", file=sys.stderr)
        return 1
    if not d.get("checked"):
        print(f"audit: not checked ({d.get('note')})")
        return 0
    verb = "handed over" if d.get("applied") else "would move"
    print(f"audit: {d.get('read')} open items read · {d.get('found')} with a mover that is gone · {len(d.get('moved') or [])} {verb} · {len(d.get('left') or [])} with no live successor" + ("" if d.get("applied") else " (a dry run: nothing written, nobody told)"))
    if not d.get("applied") and d.get("note"):
        print(f"audit: {d['note']}")
    for m in d.get("moved") or []:
        print(f"  {m.get('id')} · {m.get('from') or 'no session'} → {m.get('to')} · {m.get('why')}")
    for m in d.get("left") or []:
        print(f"  {m.get('id')} · {m.get('from') or 'no session'} · no live agent to take it ({m.get('project')}): {m.get('why')}")
    if d.get("over_cap"):
        print(f"  {d['over_cap']} more over the cap of one run, left for the next")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
