"""tools/catch_report.py — the daily count of a hook's catches, per source.

Reads the catch log the server keeps (service/catches.py: one line per catch a front agent's hook posted, in `<paths.state>/catches/<YYYY-MM>.jsonl`) and reports, for one calendar day in the instance
timezone: how many catches there were, a table of them by source (router notice, stackshot message, background-agent hand-back, front peer, script, other) beside the day before, and the panes and senders that
were caught most. It reads the log and never writes it: its only record is the days it sent.

    catch_report.py run [--dry-run] [--force] [--day YYYY-MM-DD]
    audit.py catches [--dry-run] [--force] [--day YYYY-MM-DD]       the same, from the audit's own entry point (the timer's unit runs it after the audit run)

  run           the report of yesterday (the last full day), sent once to `[catch_report] to` (default: `[audit] summary_to`), as a message that asks nothing (fyi). The audit's timer runs this twice a day, so
                the report goes out at the first run after the day ends, and never twice for one day (`<paths.state>/catch-report/sent.json` keeps the days sent). A day with no catches is not sent.
  --dry-run     print the report and send nothing, mark nothing; it works while `[catch_report] enabled` is false
  --force       report the day even if it was sent already (the record is rewritten)
  --day DATE    that day (YYYY-MM-DD) instead of yesterday

`[catch_report]` in stackshot.toml: enabled (default false: nothing is sent), to, top (panes and senders listed, default 5), sender (default "stackshot catch report").
Stdlib plus the repo's modules."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import collections
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.service import catches as _catches  # noqa: E402

SENDER = "stackshot catch report"
TOP_DEFAULT = 5
SOURCES = _catches.SOURCES


def settings() -> dict[str, Any]:
    """[catch_report] from the instance config, defaults filled in."""
    c = _cfg.get("catch_report") or {}
    top = c.get("top")
    return {
        "enabled": c.get("enabled") is True or str(c.get("enabled")).strip().lower() in ("true", "1", "yes"),
        "to": str(c.get("to") or "").strip() or _cfg.audit_summary_to(),
        "top": top if isinstance(top, int) and 1 <= top <= 20 else TOP_DEFAULT,
        "sender": str(c.get("sender") or "").strip() or SENDER,
    }


def state_file() -> Path:
    return _cfg.state("catch-report") / "sent.json"          # the folder is made only when a report is recorded (a dry run makes nothing)


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of a day's catch lines: {"total", "sources": Counter, "panes": Counter, "senders": Counter}. A source the code does not know counts as `other`."""
    sources: collections.Counter = collections.Counter()
    panes: collections.Counter = collections.Counter()
    senders: collections.Counter = collections.Counter()
    for r in rows:
        s = str(r.get("source") or "")
        sources[s if s in SOURCES else "other"] += 1
        panes[str(r.get("pane") or "-")] += 1
        senders[str(r.get("sender") or "-")] += 1
    return {"total": sum(sources.values()), "sources": sources, "panes": panes, "senders": senders}


def collect(day: dt.date) -> tuple[dict[str, Any], dict[str, Any]]:
    """(the day's counts, the day before's)."""
    return (tally(_catches.read_day(day.isoformat())), tally(_catches.read_day((day - dt.timedelta(days=1)).isoformat())))


def table(day: dt.date, cur: dict[str, Any], prev: dict[str, Any]) -> list[str]:
    """The per-source table, one column for the day and one for the day before, each source of SOURCES a row (a source with none reads 0), then the total."""
    heads = (_catches.shown_day(day), _catches.shown_day(day - dt.timedelta(days=1)))
    rows = [(s, cur["sources"].get(s, 0), prev["sources"].get(s, 0)) for s in SOURCES] + [("total", cur["total"], prev["total"])]
    w0 = max(len("source"), *(len(r[0]) for r in rows))
    w1, w2 = max(len(heads[0]), 5), max(len(heads[1]), 5)
    out = [f"{'source':<{w0}}  {heads[0]:>{w1}}  {heads[1]:>{w2}}"]
    out += [f"{name:<{w0}}  {a:>{w1},}  {b:>{w2},}" for name, a, b in rows]
    return out


def build(day: dt.date, cur: dict[str, Any], prev: dict[str, Any], *, top: int = TOP_DEFAULT) -> str:
    """The report text of `day`: the counts of that day (`cur`) and the day before (`prev`), from tally()."""
    z = _cfg.tz_abbr(dt.datetime.combine(day, dt.time(12, 0)))
    lines = [f"Hook catches, {_catches.shown_day(day)} ({z}): {cur['total']:,}" + (f"; the day before {prev['total']:,}" if prev["total"] else "; no catches recorded for the day before")]
    lines += ["```", *table(day, cur, prev), "```"]
    if cur["panes"]:
        lines.append("- caught most: " + " · ".join(f"{k} {v:,}" for k, v in cur["panes"].most_common(top)))
        lines.append("- turns started by: " + " · ".join(f"{k} {v:,}" for k, v in cur["senders"].most_common(top)))
    return "\n".join(lines)


def _read_sent(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"days": []}
    return d if isinstance(d, dict) and isinstance(d.get("days"), list) else {"days": []}


def _write_sent(p: Path, d: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, p)


Deliver = Callable[[str, str, str], tuple[bool, str]]


def deliver_client(to: str, text: str, sender: str) -> tuple[bool, str]:
    """One message that asks nothing (fyi) through client.py (this box's token) -> (delivered, the server's answer)."""
    from stackshot.fleet import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, sender, fyi=True)
    return status == 200, f"[{status}] {said}"


def run(*, dry: bool = False, force: bool = False, day: dt.date | None = None, now: float | None = None, cfg: dict[str, Any] | None = None,
        deliver: Deliver = deliver_client, state: Path | None = None) -> dict[str, Any]:
    """-> {"day": the date, "text": the report, "sent": bool, "why": what happened}. Sends the report of yesterday (or `day`) once."""
    cfg = cfg or settings()
    today = dt.datetime.fromtimestamp(time.time() if now is None else now, _cfg.tz()).date()
    d = day or today - dt.timedelta(days=1)
    sp = state or state_file()
    done = _read_sent(sp)
    key = d.isoformat()
    if key in done["days"] and not force and not dry:
        return {"day": d, "text": "", "sent": False, "why": "already sent"}
    cur, prev = collect(d)
    if not cur["total"]:
        return {"day": d, "text": "", "sent": False, "why": "no catches recorded for the day"}
    text = build(d, cur, prev, top=cfg["top"])
    if dry:
        return {"day": d, "text": text, "sent": False, "why": "dry run"}
    if not cfg["enabled"]:
        return {"day": d, "text": text, "sent": False, "why": "not enabled ([catch_report] enabled)"}
    ok, said = deliver(cfg["to"], text, cfg["sender"])
    if not ok:
        return {"day": d, "text": text, "sent": False, "why": said}
    done["days"] = sorted({*done["days"], key})[-120:]
    try:
        _write_sent(sp, done)
    except OSError as e:          # the report is out: a record that cannot be written is reported as such, not raised as a failed send
        return {"day": d, "text": text, "sent": True, "why": f"sent to {cfg['to']}, but not recorded ({e}): the next run will send it again until the record can be written"}
    return {"day": d, "text": text, "sent": True, "why": f"sent to {cfg['to']}"}


def main(argv: list[str]) -> int:
    a = list(argv)
    if a and a[0] == "run":
        a = a[1:]
    dry, force, day = False, False, None
    while a:
        k = a.pop(0)
        if k == "--dry-run":
            dry = True
        elif k == "--force":
            force = True
        elif k == "--day" and a:
            try:
                day = dt.date.fromisoformat(a.pop(0))
            except ValueError:
                print("catch report: --day takes a date, YYYY-MM-DD", file=sys.stderr)
                return 2
        else:
            print("usage: catch_report.py run [--dry-run] [--force] [--day YYYY-MM-DD]", file=sys.stderr)
            return 2
    res = run(dry=dry, force=force, day=day)
    if res["text"]:
        print(res["text"])
    print(f"catch report: {res['why']}" + (f" (day {res['day']})" if res.get("day") else ""))
    return 0 if res["sent"] or res["why"] in ("dry run", "already sent", "no catches recorded for the day") or res["why"].startswith("not enabled") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
