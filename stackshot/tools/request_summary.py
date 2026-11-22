"""request_summary.py: `stackshot requests summary`, the server's request log read back (core/requestlog.py writes it, docs/request-log.md describes it).

    python3 -m stackshot requests summary [--since 24h] [--until now] [--top 10] [--route SUBSTRING] [--json] [--dir DIR] [--tz ZONE]

`--since` and `--until` take a date (2026-11-22), a date and time (2026-11-22T14:30) or a time back from now (90m, 24h, 7d). A date or time with no offset is in the instance's timezone ([instance] timezone, which is also the
zone every time is printed in); a bare date in `--until` means the end of that day. The default range is the last 24 hours.

The output: a table per route (count, p50, p95 and max of the time in ms, and the 5xx count), the slowest calls, the errors (a 5xx or a line with an `err`: the count and the first few), the server starts of the range, and the
totals (requests and the error rate). A percentile is the value at position ceil(q x n) of the n times in order (p95 of 20 times is the 19th). `--route` keeps the requests whose route holds the text; `--json` prints the same as JSON.
An empty range prints "no requests in range" and exits 0.

Stdlib only at import (the config is read only when `--dir` or `--tz` is left out)."""
from __future__ import annotations

import argparse
import datetime as dt
import heapq
import json
import math
import re
import sys
import time
from typing import Any
from zoneinfo import ZoneInfo

from stackshot.core import requestlog as _log

ERRORS_SHOWN = 5          # the errors printed (the count is of all of them)
_REL = re.compile(r"^(\d+)([mhd])$")


def parse_when(text: str, tz: Any, *, now: float, end: bool = False) -> float:
    """`--since` / `--until` text → epoch seconds. 90m, 24h, 7d count back from `now`; an ISO date or date-time is in `tz` unless it carries an offset or a Z; `end` makes a bare date the end of that day."""
    s = text.strip()
    m = _REL.match(s)
    if m:
        return now - int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    if s.lower() == "now":
        return now
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"not a date, a date and time or a time back from now (90m, 24h, 7d): {text!r}") from None
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    t = d.timestamp()
    if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        t = (d + dt.timedelta(days=1)).timestamp()      # the date's own end (a day is 23 or 25 hours across a clock change)
    return t


def percentile(sorted_ms: list[float], q: float) -> float:
    """The percentile of a sorted list: the value at position ceil(q x n)."""
    return sorted_ms[max(0, math.ceil(q * len(sorted_ms)) - 1)]


def summarize(records: Any, *, top: int = 10, route: str = "") -> dict[str, Any]:
    """The records (dicts as core/requestlog.read yields them) → the summary as plain data, times still epoch seconds."""
    per: dict[str, list[float]] = {}
    fives: dict[str, int] = {}
    slow: list[tuple[float, int, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    n_err = n = 0
    seq = 0
    events: list[dict[str, Any]] = []
    for r in records:
        if r.get("kind"):
            if r.get("kind") in ("start", "stop"):
                events.append(r)
            continue
        rt = str(r.get("route") or "?")
        if route and route not in rt:
            continue
        try:
            ms = float(r.get("ms") or 0.0)
        except (TypeError, ValueError):
            continue
        st = r.get("status") if isinstance(r.get("status"), int) else 0
        n += 1
        per.setdefault(rt, []).append(ms)
        is5 = st >= 500
        if is5:
            fives[rt] = fives.get(rt, 0) + 1
        if is5 or r.get("err"):
            n_err += 1
            errors.append(r)
        seq += 1
        if top > 0:
            item = (ms, seq, r)
            if len(slow) < top:
                heapq.heappush(slow, item)
            elif item > slow[0]:
                heapq.heapreplace(slow, item)
    routes = []
    for rt, ms_list in per.items():
        ms_list.sort()
        routes.append({"route": rt, "count": len(ms_list), "p50": percentile(ms_list, 0.5), "p95": percentile(ms_list, 0.95), "max": ms_list[-1], "errors5xx": fives.get(rt, 0)})
    routes.sort(key=lambda x: (-x["count"], x["route"]))
    return {"requests": n, "errors": n_err, "error_rate": (n_err / n) if n else 0.0, "routes": routes,
            "slowest": [r for _, _, r in sorted(slow, reverse=True)], "error_lines": errors, "events": events}


def _fmt_t(t: float, tz: Any) -> str:
    return dt.datetime.fromtimestamp(t, tz).strftime("%Y-%m-%d %H:%M:%S")


def _num(v: float) -> str:
    return f"{v:.1f}"


def render_text(s: dict[str, Any], tz: Any, tzname: str, since: float, until: float) -> str:
    out = [f"requests from {_fmt_t(since, tz)} to {_fmt_t(until, tz)} ({tzname})"]
    if not s["requests"]:
        out += ["", "no requests in range"]
        if not s["events"]:
            return "\n".join(out)
    else:
        w = max(5, min(48, max(len(r["route"]) for r in s["routes"])))
        out += ["", f"{'route':<{w}} {'count':>7} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>9} {'5xx':>5}"]
        out += [f"{r['route'][:w]:<{w}} {r['count']:>7} {_num(r['p50']):>8} {_num(r['p95']):>8} {_num(r['max']):>9} {r['errors5xx']:>5}" for r in s["routes"]]
        out += ["", "slowest calls"]
        out += [f"  {_fmt_t(r['_t'], tz)}  {str(r.get('route'))[:48]:<48} {_num(float(r.get('ms') or 0)):>9} ms  {r.get('status')}  {r.get('caller', 'anon')}" for r in s["slowest"]]
        out += ["", f"errors: {s['errors']}"]
        out += [f"  {_fmt_t(r['_t'], tz)}  {r.get('method', '')} {r.get('route')}  {r.get('status')}  {r.get('err', '')}".rstrip() for r in s["error_lines"][:ERRORS_SHOWN]]
        if s["errors"] > ERRORS_SHOWN:
            out.append(f"  ... and {s['errors'] - ERRORS_SHOWN} more")
    out += ["", "server starts and stops"]
    ev = [f"  {_fmt_t(r['_t'], tz)}  {r['kind']}" + (f"  pid {r['pid']}" if r.get("pid") else "") + (f"  head {r['head']}" if r.get("head") else "") + (f"  mode {r['mode']}" if r.get("mode") else "")
          for r in s["events"]]
    out += ev or ["  none in range"]
    if s["requests"]:
        out += ["", f"totals: {s['requests']} requests, {s['errors']} errors ({s['error_rate'] * 100:.2f}%)"]
    return "\n".join(out)


def as_json(s: dict[str, Any], tz: Any, tzname: str, since: float, until: float) -> dict[str, Any]:
    t = lambda x: dt.datetime.fromtimestamp(x, tz).isoformat(timespec="milliseconds")
    keep = lambda r: {k: v for k, v in r.items() if k not in ("ts", "_t")} | {"time": t(r["_t"])}
    return {"range": {"since": t(since), "until": t(until), "timezone": tzname}, "totals": {"requests": s["requests"], "errors": s["errors"], "error_rate": round(s["error_rate"], 6)},
            "routes": s["routes"], "slowest": [keep(r) for r in s["slowest"]], "errors": {"count": s["errors"], "first": [keep(r) for r in s["error_lines"][:ERRORS_SHOWN]]},
            "events": [keep(r) for r in s["events"]]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stackshot requests", description="The server's request log.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="per-route times, the slowest calls, the errors and the server starts of a range",
                       description="Read <state>/requests (plain and gzipped day files) and print p50 and p95 per route, the slowest calls, the errors, the server starts and the totals.")
    s.add_argument("--since", default="24h", help="start of the range: a date, a date and time, or 90m / 24h / 7d back from now (default 24h)")
    s.add_argument("--until", default="now", help="end of the range (default now); a bare date means the end of that day")
    s.add_argument("--top", type=int, default=10, help="how many of the slowest calls to list (default 10)")
    s.add_argument("--route", default="", help="only the requests whose route contains this text")
    s.add_argument("--json", action="store_true", help="print JSON instead of the table")
    s.add_argument("--dir", help="the directory of the day files (default <state>/requests)")
    s.add_argument("--tz", help="the zone times are read and printed in (default [instance] timezone)")
    a = p.parse_args(argv)
    try:
        tzname = a.tz or ""
        if not tzname or not a.dir:
            from stackshot.core import config as _cfg
            tzname = tzname or str(_cfg.get("instance", "timezone") or "UTC")
            directory = a.dir or str(_cfg.state("requests"))
        else:
            directory = a.dir
        tz = ZoneInfo(tzname)
        now = time.time()
        since, until = parse_when(a.since, tz, now=now), parse_when(a.until, tz, now=now, end=True)
    except (ValueError, KeyError, OSError) as e:
        print(f"stackshot requests: {e}", file=sys.stderr)
        return 2
    if until <= since:
        print("stackshot requests: the range is empty: --until is not after --since", file=sys.stderr)
        return 2
    summary = summarize(_log.read(directory, since, until), top=a.top, route=a.route)
    if a.json:
        print(json.dumps(as_json(summary, tz, tzname, since, until), indent=2, ensure_ascii=False))
    else:
        print(render_text(summary, tz, tzname, since, until))
    return 0


if __name__ == "__main__":
    sys.exit(main())
