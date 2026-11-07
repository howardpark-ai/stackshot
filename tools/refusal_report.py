#!/usr/bin/env python3
"""tools/refusal_report.py — the weekly count of board writes the server refused.

Reads the call log the server keeps (call_log.py: one line per create, update, complete, confirm and message call, went through or refused, in
`<paths.state>/calls/<YYYY-MM>.jsonl`) and reports, for one calendar week Monday to Sunday in the instance timezone: how many create and update calls
were refused of how many, the share, the week before it, the kinds of refusal that make most of them, the sessions that were refused most, and what the
server corrected instead of refusing (a bare item number, a wake with seconds or an offset, a subject with no scope prefix). Tokenless: no model call.

    refusal_report.py run [--dry-run] [--force] [--week YYYY-MM-DD]
    audit.py refusals [--dry-run] [--force] [--week YYYY-MM-DD]       the same, from the audit's own entry point (the timer's unit runs it after the audit run)

  run           the report of the last full week (Monday to Sunday) that has not been sent, sent once to `[refusal_report] to` (default: `[audit] summary_to`),
                as a message that asks nothing (fyi). The audit's timer runs this twice a day, so the report goes out at the first run after the week ends, and
                never twice for one week (`<paths.state>/refusal-report/sent.json` keeps the weeks sent). A week with no call records is not sent.
  --dry-run     print the report and send nothing, mark nothing; it works while `[refusal_report] enabled` is false
  --force       report the week even if it was sent already (the record is rewritten)
  --week DATE   the week that starts on that Monday (YYYY-MM-DD) instead of the last full one

`[refusal_report]` in stackshot.toml: enabled (default false: nothing is sent), to, top (kinds listed, default 6), sender (default "stackshot refusal report").
Stdlib plus the repo's modules."""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parent
sys.path.insert(0, str(CHECKOUT))
import call_log as _cl  # noqa: E402
import config as _cfg  # noqa: E402

SENDER = "stackshot refusal report"
HEADLINE = ("create", "update")          # the calls the share is measured on
TOP_DEFAULT = 6
SENDERS_TOP = 5


def settings() -> dict[str, Any]:
    """[refusal_report] from the instance config, defaults filled in."""
    c = _cfg.get("refusal_report") or {}
    top = c.get("top")
    return {
        "enabled": c.get("enabled") is True or str(c.get("enabled")).strip().lower() in ("true", "1", "yes"),
        "to": str(c.get("to") or "").strip() or _cfg.audit_summary_to(),
        "top": top if isinstance(top, int) and 1 <= top <= 20 else TOP_DEFAULT,
        "sender": str(c.get("sender") or "").strip() or SENDER,
    }


def state_file() -> Path:
    return _cfg.state("refusal-report") / "sent.json"          # the folder is made only when a report is recorded (a dry run makes nothing)


def week_start(day: dt.date) -> dt.date:
    """The Monday on or before `day`."""
    return day - dt.timedelta(days=day.weekday())


def week_bounds(monday: dt.date) -> tuple[float, float]:
    """(epoch of Monday 00:00, epoch of the next Monday 00:00) in the instance timezone."""
    z = _cfg.tz()
    a = dt.datetime.combine(monday, dt.time(0, 0), tzinfo=z)
    b = dt.datetime.combine(monday + dt.timedelta(days=7), dt.time(0, 0), tzinfo=z)
    return a.timestamp(), b.timestamp()


def _ord(n: int) -> str:
    return f"{n}th" if 10 <= n % 100 <= 20 else f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def shown(d: dt.date) -> str:
    """A date as a person reads it: Mon Nov 2nd."""
    return f"{d:%a %b} {_ord(d.day)}"


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of a list of call lines: {"calls": {tool: n}, "refused": {tool: n}, "kinds": Counter, "senders": Counter, "fixes": Counter, "first": epoch of the first line or None}."""
    calls: collections.Counter = collections.Counter()
    refused: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    senders: collections.Counter = collections.Counter()
    fixes: collections.Counter = collections.Counter()
    first = None
    for r in rows:
        tool = str(r.get("tool") or "")
        calls[tool] += 1
        first = r["t"] if first is None else min(first, r["t"])
        if r.get("ok") is False:
            refused[tool] += 1
            if tool in HEADLINE:
                kinds[_cl.kind_of(str(r.get("why") or ""))] += 1
                senders[str(r.get("sender") or "-")] += 1
        else:
            for k in r.get("fix") or []:
                fixes[str(k)] += 1
    return {"calls": dict(calls), "refused": dict(refused), "kinds": kinds, "senders": senders, "fixes": fixes, "first": first}


def _share(refused: int, calls: int) -> str:
    return f"{refused / calls * 100:.1f}%" if calls else "n/a"


def _headline(t: dict[str, Any]) -> tuple[int, int]:
    return sum(t["refused"].get(x, 0) for x in HEADLINE), sum(t["calls"].get(x, 0) for x in HEADLINE)


def build(monday: dt.date, cur: dict[str, Any], prev: dict[str, Any], *, top: int = TOP_DEFAULT) -> str:
    """The report text of the week starting `monday`: the counts of that week (`cur`) and the week before (`prev`), from tally()."""
    r, n = _headline(cur)
    pr, pn = _headline(prev)
    sunday = monday + dt.timedelta(days=6)
    z = _cfg.tz()
    lines = [f"Refused board writes, {shown(monday)} to {shown(sunday)} ({_cfg.tz_abbr(dt.datetime.combine(monday, dt.time(12, 0)))}):"]
    lines.append(f"- create and update: {r:,} of {n:,} calls refused ({_share(r, n)})" + (f"; the week before {pr:,} of {pn:,} ({_share(pr, pn)})" if pn else "; no records for the week before"))
    others = [(t, cur["refused"].get(t, 0), c) for t, c in sorted(cur["calls"].items()) if t not in HEADLINE and cur["refused"].get(t, 0)]
    if others:
        lines.append("- other writes refused: " + " · ".join(f"{t} {x:,} of {c:,}" for t, x, c in others))
    if r:
        lines.append("- the kinds of create and update refusals: " + " · ".join(f"{k} {v:,} ({v / r * 100:.0f}%)" for k, v in cur["kinds"].most_common(top)))
        rest = sum(cur["kinds"].values()) - sum(v for _, v in cur["kinds"].most_common(top))
        if rest > 0:
            lines[-1] += f" · {rest:,} in other kinds"
        lines.append("- refused most: " + " · ".join(f"{s} {v:,}" for s, v in cur["senders"].most_common(SENDERS_TOP)))
    if cur["fixes"]:
        total = sum(cur["fixes"].values())
        lines.append(f"- corrected by the server instead of refused: {total:,} (" + " · ".join(f"{k} {v:,}" for k, v in cur["fixes"].most_common()) + ")")
    first = cur["first"]
    if first is not None and first > week_bounds(monday)[0] + 12 * 3600:
        lines.append(f"- the call log starts {shown(dt.datetime.fromtimestamp(first, z).date())}: the days before it are not counted")
    return "\n".join(lines)


def collect(monday: dt.date) -> tuple[dict[str, Any], dict[str, Any]]:
    a, b = week_bounds(monday)
    p, _ = week_bounds(monday - dt.timedelta(days=7))
    return tally(list(_cl.read(a, b))), tally(list(_cl.read(p, a)))


def _read_sent(p: Path) -> dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"weeks": []}
    return d if isinstance(d, dict) and isinstance(d.get("weeks"), list) else {"weeks": []}


def _write_sent(p: Path, d: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, p)


Deliver = Callable[[str, str, str], tuple[bool, str]]


def deliver_client(to: str, text: str, sender: str) -> tuple[bool, str]:
    """One message that asks nothing (fyi) through client.py (this box's token) → (delivered, the server's answer)."""
    import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, sender, fyi=True)
    return status == 200, f"[{status}] {said}"


def run(*, dry: bool = False, force: bool = False, week: dt.date | None = None, now: float | None = None, cfg: dict[str, Any] | None = None,
        deliver: Deliver = deliver_client, state: Path | None = None) -> dict[str, Any]:
    """→ {"week": the Monday, "text": the report, "sent": bool, "why": what happened}. Sends the report of the last full week (or `week`) once."""
    cfg = cfg or settings()
    today = dt.datetime.fromtimestamp(time.time() if now is None else now, _cfg.tz()).date()
    monday = week or week_start(today) - dt.timedelta(days=7)
    if week is not None and week.weekday() != 0:
        return {"week": week, "text": "", "sent": False, "why": f"{week} is not a Monday"}
    sp = state or state_file()
    done = _read_sent(sp)
    key = monday.isoformat()
    if key in done["weeks"] and not force and not dry:
        return {"week": monday, "text": "", "sent": False, "why": "already sent"}
    cur, prev = collect(monday)
    if not cur["calls"]:
        return {"week": monday, "text": "", "sent": False, "why": "no call records for the week"}
    text = build(monday, cur, prev, top=cfg["top"])
    if dry:
        return {"week": monday, "text": text, "sent": False, "why": "dry run"}
    if not cfg["enabled"]:
        return {"week": monday, "text": text, "sent": False, "why": "not enabled ([refusal_report] enabled)"}
    ok, said = deliver(cfg["to"], text, cfg["sender"])
    if not ok:
        return {"week": monday, "text": text, "sent": False, "why": said}
    done["weeks"] = sorted({*done["weeks"], key})[-60:]
    try:
        _write_sent(sp, done)
    except OSError as e:          # the report is out: a record that cannot be written is reported as such, not raised as a failed send
        return {"week": monday, "text": text, "sent": True, "why": f"sent to {cfg['to']}, but not recorded ({e}): the next run will send it again until the record can be written"}
    return {"week": monday, "text": text, "sent": True, "why": f"sent to {cfg['to']}"}


def main(argv: list[str]) -> int:
    a = list(argv)
    if a and a[0] == "run":
        a = a[1:]
    dry, force, week = False, False, None
    while a:
        k = a.pop(0)
        if k == "--dry-run":
            dry = True
        elif k == "--force":
            force = True
        elif k == "--week" and a:
            try:
                week = dt.date.fromisoformat(a.pop(0))
            except ValueError:
                print("refusal report: --week takes a date, YYYY-MM-DD", file=sys.stderr)
                return 2
        else:
            print("usage: refusal_report.py run [--dry-run] [--force] [--week YYYY-MM-DD]", file=sys.stderr)
            return 2
    res = run(dry=dry, force=force, week=week)
    if res["text"]:
        print(res["text"])
    print(f"refusal report: {res['why']}" + (f" (week of {res['week']})" if res.get("week") else ""))
    return 0 if res["sent"] or res["why"] in ("dry run", "already sent", "no call records for the week") or res["why"].startswith("not enabled") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
