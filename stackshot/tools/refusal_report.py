"""tools/refusal_report.py — the weekly count of board writes the server refused.

Reads the call log the server keeps (call_log.py: one line per call of every tool, went through or refused, in `<paths.state>/calls/<YYYY-MM>.jsonl`; the weekly count below reads the lines of the five
writes, create, update, complete, confirm and message, the daily analysis all of them) and reports, for one calendar week Monday to Sunday in the instance timezone: how many create and update calls
were refused of how many, the share, the week before it, the kinds of refusal that make most of them, the sessions that were refused most, and what the
server corrected instead of refusing (a bare item number or #N in any call that takes an item id, a close included, read as board#N, a close that names its replacing item and no outcome read as superseded (outcome-superseded), a message's page key spelled another way, a wake with seconds or an offset, a subject with no scope prefix, a long description or outcome_text bullet split at its sentence ends or, for one clause, at a comma, colon, dash or parenthesis, or, with no such cut, cut at a space onto an indented line under it (bullet-wrap, or outcome-wrap for an outcome_text),
a step left out of next kept open, a subject or a status line cut at its last word that fits, an ask-by with a time of day cut to its day, a bare address in a description written as a link, the server's own fixes of a wait), and how many of those fixes the writer sent back (call_log.bounces; of the fixes of the kinds that have the check, call_log.CHECKED), and the streaks: one writer refused STREAK_MIN (3) times or more on one call (the same tool and item) with each refusal within STREAK_WINDOW (15 minutes) of the one before, counted by kind and listed first, since a streak marks a gap in the tool text. Message calls have lines of their own (the message tool and the client route's script messages, `_message_lines`): the calls refused of all with the week before, the refusals by the kind slug the call log keeps (`service/messaging.py` `Refused`; `not recorded` for a line from before kinds were logged), the streaks of one sender refused MSG_STREAK_MIN (2) times or more on one target within MSG_STREAK_WINDOW (an hour) of the one before, how many of them also meet the rule above (3 within 15 minutes), and the refusals sent again within RESEND_WINDOW (an hour) with a similar text by the same sender (`similar`: difflib ratio of at least SIMILAR, 0.5), to the same target or another, looked for in the later refusals and in the delivered messages of the message log (`messages.jsonl`, `delivered`). One more line, when the week or the one before it had any: the wait loops the minute walk found (audit/wait_loops.py: items that wait on each other), counted from its log. Tokenless: no model call.

    refusal_report.py run [--dry-run] [--force] [--week YYYY-MM-DD]
    audit.py refusals [--dry-run] [--force] [--week YYYY-MM-DD]       the same, from the audit's own entry point (the timer's unit runs it after the audit run); without --week it then runs the daily analysis below
    refusal_report.py daily [--dry-run] [--force]                      the daily analysis alone

  daily         every tool's calls (reads too: a read that errors counts as refused) for the last 24 hours and the last 7 days: refusals per tool, per rule kind and per caller session; the retries (the same caller repeating the same tool on the same item within
                RETRY_WINDOW, 10 minutes, after a refusal); the tokens of refusal text plus retried requests (characters / 4, an estimate: the log keeps sizes, `req` and `rlen`, never content); and the kinds refused REPEAT_MIN (3) times or more in the
                day, each with its line from HINTS (or the line of NO_HINT saying why none fits) or "needs a fix". Sent once per calendar day (the audit's 05:00 run; its 20:00 run finds it sent) to the same place as the weekly report, when there was a refusal in the last 24 hours; the background agent
                gets it too when a repeating kind needs a fix. A line of the log from before sizes were kept counts as a call of no size. No new timer and no new config key: the days sent are kept in the weekly report's sent.json.

  run           the report of the last full week (Monday to Sunday) that has not been sent, sent once to `[refusal_report] to` (default: `[audit] summary_to`),
                as a message that asks nothing (fyi). The audit's timer runs this twice a day, so the report goes out at the first run after the week ends, and
                never twice for one week (`<paths.state>/refusal-report/sent.json` keeps the weeks sent). A week with no call records is not sent.
                The page copy is the fyi above. The same report also goes, as a normal message that asks for something, to the project's background agent
                (anchors.background_ranked of the `to` page: the builder first, else the first of the others), asking it to file a write-time hint or a server fix for each kind that repeats.
                A `to` that is a session name, or a project with no background agent, gets the page copy alone.
  --dry-run     print the report and send nothing, mark nothing; it works while `[refusal_report] enabled` is false
  --force       report the week even if it was sent already (the record is rewritten)
  --week DATE   the week that starts on that Monday (YYYY-MM-DD) instead of the last full one

`[refusal_report]` in stackshot.toml: enabled (default false: nothing is sent), to, top (kinds listed, default 6), sender (default "stackshot refusal report").
Stdlib plus the repo's modules."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import collections
import datetime as dt
import difflib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
from stackshot.core import call_log as _cl  # noqa: E402
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.core.lines import newline_lines  # noqa: E402

SENDER = "stackshot refusal report"
HEADLINE = ("create", "update")          # the calls the share is measured on
TOP_DEFAULT = 6
SENDERS_TOP = 5
STREAK_WINDOW = 15 * 60                  # seconds: a refusal joins a streak when the writer's last refusal on the same call was no more than this long before it
STREAK_MIN = 3                           # a streak is this many refusals or more: a writer refused again and again on one call has hit a gap in its instructions (the tool text)
MSG_STREAK_WINDOW = 3600                 # seconds: a refused message joins a message streak when the same sender's last refusal to the same target was no more than this long before it
MSG_STREAK_MIN = 2                       # a message streak is this many refusals or more (a message names no item the log could key on: the pair of sender and target is the call)
RESEND_WINDOW = 3600                     # seconds: a message of the same sender that comes this soon after a refusal, with a similar text, is the refused message sent again
SIMILAR = 0.5                            # difflib ratio of the two texts (case and spacing folded, the first SIMILAR_CHARS characters) from which one is the other sent again
SIMILAR_CHARS = 1000
NO_KIND = "not recorded"                 # a refused message of a week before kinds were logged


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


NO_WHY = "unknown"                       # a refused line of the first format has no text: it is counted and shown under this, not as an empty kind


def _kind_of_why(why: str) -> str:
    """call_log.kind_of, NO_WHY for a refusal with no text."""
    return _cl.kind_of(why) or NO_WHY


def streaks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The streaks in the refused lines of `rows`: one writer (sender) refused STREAK_MIN times or more on one call (the same tool and item, for a create the same `call` digest), each refusal within STREAK_WINDOW of the one before it.
    → [{"kind": the kind most of its refusals are counted under (the later one on a tie), "tool", "sender", "item", "n": its refusals}]; a call that is not create or update has its tool before the kind."""
    by: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        call = str(r.get("item") or "") or str(r.get("call") or "")          # a refused create has no item: its `call` digest tells one from another; a line with neither is no call to count
        if r.get("ok") is False and call:
            by[(str(r.get("sender") or "-"), str(r.get("tool") or ""), call)].append(r)
    out: list[dict[str, Any]] = []
    for (who, tool, item), got in by.items():
        got.sort(key=lambda r: r["t"])
        run_: list[dict[str, Any]] = []
        for r in [*got, None]:
            if r is not None and run_ and r["t"] - run_[-1]["t"] <= STREAK_WINDOW:
                run_.append(r)
                continue
            if len(run_) >= STREAK_MIN:
                kinds = [_kind_of_why(str(x.get("why") or "")) for x in run_]
                most = collections.Counter(kinds)
                kind = [k for k in kinds if most[k] == max(most.values())][-1]
                out.append({"kind": kind if tool in HEADLINE else f"{tool}: {kind}", "tool": tool, "sender": who, "item": item, "n": len(run_)})
            run_ = [r] if r is not None else []
    return out


def _runs(got: list[dict[str, Any]], window: float, minimum: int) -> list[list[dict[str, Any]]]:
    """The runs in `got` (rows sorted by time): each row within `window` seconds of the one before it, kept when it holds `minimum` rows or more."""
    out: list[list[dict[str, Any]]] = []
    run_: list[dict[str, Any]] = []
    for r in [*got, None]:
        if r is not None and run_ and r["t"] - run_[-1]["t"] <= window:
            run_.append(r)
            continue
        if len(run_) >= minimum:
            out.append(run_)
        run_ = [r] if r is not None else []
    return out


def _fold(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def similar(a: Any, b: Any) -> bool:
    """Is one message the other sent again: the texts equal once case and spacing are folded, or the difflib ratio of their first SIMILAR_CHARS characters at least SIMILAR (deterministic; an empty text is similar to nothing)."""
    x, y = _fold(a)[:SIMILAR_CHARS], _fold(b)[:SIMILAR_CHARS]
    if not x or not y:
        return False
    if x == y:
        return True
    m = difflib.SequenceMatcher(None, x, y, autojunk=False)
    return m.real_quick_ratio() >= SIMILAR and m.quick_ratio() >= SIMILAR and m.ratio() >= SIMILAR


def message_stats(rows: list[dict[str, Any]], sent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What the call lines say of the message calls: {"calls", "refused", "kinds": Counter (by `kind`, NO_KIND for a line from before kinds were logged), "handled": Counter of (kind, how) of the calls the relay handled where it once refused (a line with `outcome: handled`: counted in "calls", never in "refused"),
    "streaks": [{"sender", "to", "n", "kind": the kind most of its refusals are (the later one on a tie), "tight": it holds STREAK_MIN refusals or more within STREAK_WINDOW, the report's own rule}] (one sender refused MSG_STREAK_MIN times or more on one target,
    each refusal within MSG_STREAK_WINDOW of the one before it; a message names no item the log could key on, so the pair of sender and target is the call), "streak_refusals": the refusals they hold, "tight": how many of the streaks are tight,
    "resent": {"same": refusals sent again to the same target, "other": sent again to another target}}. A refusal is sent again when, within RESEND_WINDOW after it, the same sender's message reads as its text (`similar`): a later refusal in `rows`
    or a message in `sent` (the delivered messages [{"t", "from", "to", "text"}], from `delivered`); each refusal counts once, under the first such message. A line with no target or no text (from before they were logged) is in no streak and no resend."""
    calls = refused = 0
    kinds: collections.Counter = collections.Counter()
    handled: collections.Counter = collections.Counter()
    refs: list[dict[str, Any]] = []
    for r in rows:
        if str(r.get("tool") or "") != "message":
            continue
        calls += 1
        if r.get("ok") is True and r.get("outcome") == "handled":          # a call the relay handled where it once refused (call_log.handled): it went through, under the kind of the refusal it replaced
            handled[(str(r.get("kind") or "") or NO_KIND, str(r.get("how") or ""))] += 1
        if r.get("ok") is False:
            refused += 1
            kinds[str(r.get("kind") or "") or NO_KIND] += 1
            refs.append(r)
    pair: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in refs:
        if str(r.get("to") or "").strip():
            pair[(_fold(r.get("sender") or "-"), _fold(r.get("to")))].append(r)
    runs: list[dict[str, Any]] = []
    held = tight = 0
    for got in pair.values():
        got.sort(key=lambda r: r["t"])
        close = _runs(got, STREAK_WINDOW, STREAK_MIN)
        for run_ in _runs(got, MSG_STREAK_WINDOW, MSG_STREAK_MIN):
            ks = [str(x.get("kind") or "") or NO_KIND for x in run_]
            most = collections.Counter(ks)
            is_tight = any(c[0] in run_ for c in close)
            runs.append({"sender": str(run_[0].get("sender") or "-"), "to": str(run_[0].get("to")), "n": len(run_), "kind": [k for k in ks if most[k] == max(most.values())][-1], "tight": is_tight})
            held += len(run_)
            tight += is_tight
    heard = [{"t": float(r["t"]), "from": _fold(r.get("sender") or "-"), "to": _fold(r.get("to")), "text": r.get("text")} for r in refs if str(r.get("to") or "").strip() and r.get("text")]
    heard += [{"t": float(x["t"]), "from": _fold(x.get("from") or "-"), "to": _fold(x.get("to")), "text": x.get("text")} for x in sent or []]
    heard.sort(key=lambda x: x["t"])
    resent = {"same": 0, "other": 0}
    for r in refs:
        if not (str(r.get("to") or "").strip() and r.get("text")):
            continue
        who, to = _fold(r.get("sender") or "-"), _fold(r.get("to"))
        for x in heard:
            if x["t"] <= r["t"] or x["t"] - r["t"] > RESEND_WINDOW:
                continue
            if x["from"] == who and similar(r["text"], x["text"]):
                resent["same" if x["to"] == to else "other"] += 1
                break
    runs.sort(key=lambda x: (-x["n"], x["sender"], x["to"]))
    return {"calls": calls, "refused": refused, "kinds": kinds, "handled": handled, "streaks": runs, "streak_refusals": held, "tight": tight, "resent": resent}


def delivered(since: float, until: float) -> list[dict[str, Any]]:
    """The messages the relay passed on, from the message log (`<paths.state>/messages.jsonl`, service/messaging.py MSG_LOG) with since <= t < until: [{"t": epoch, "from", "to", "text"}] of the rows whose outcome says delivered, queued, inbox or held
    (a row for a message that reached no one, as a front agent's refusal leaves, is the refused call, which the call log already has). A line that does not parse is skipped; no log reads as none."""
    try:
        lines = newline_lines(_cfg.state("messages.jsonl").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            d = json.loads(ln)
            at = dt.datetime.fromisoformat(str(d["t"]))
            at = at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)
            if since <= at.timestamp() < until and str(d.get("outcome") or "").startswith(("delivered", "queued", "inbox", "held")):
                out.append({"t": at.timestamp(), "from": d.get("from"), "to": d.get("to"), "text": d.get("text")})
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return out


def tally(rows: list[dict[str, Any]], sent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The counts of a list of call lines: {"calls": {tool: n}, "refused": {tool: n}, "kinds": Counter, "senders": Counter, "fixes": Counter, "bounces": Counter, "streaks": Counter (streaks by kind), "streak_refusals": Counter (the refusals they hold, by kind), "first": epoch of the first line or None,
    "messages": message_stats(rows, sent)}. `sent` is the delivered messages of the week and the hour after it (`delivered`), where the resends of refused messages are looked for."""
    calls: collections.Counter = collections.Counter()
    refused: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    senders: collections.Counter = collections.Counter()
    fixes: collections.Counter = collections.Counter()
    bounces: collections.Counter = collections.Counter()
    first = None
    rows = [r for r in rows if str(r.get("tool") or "") in _cl.COUNTED]          # the log also holds every other tool's calls (reads): the weekly report counts the writes, as it always did; the daily analysis counts them all
    for r in rows:
        tool = str(r.get("tool") or "")
        calls[tool] += 1
        first = r["t"] if first is None else min(first, r["t"])
        if r.get("ok") is False:
            refused[tool] += 1
            if tool in HEADLINE:
                kinds[_kind_of_why(str(r.get("why") or ""))] += 1
                senders[str(r.get("sender") or "-")] += 1
        else:
            for k in r.get("fix") or []:
                fixes[str(k)] += 1
            for k in r.get("bounce") or []:
                bounces[str(k)] += 1
    bounces = collections.Counter({k: min(v, fixes[k]) for k, v in bounces.items() if fixes.get(k)})          # a send-back is of a fix: never more of a kind than the fixes of that kind (a fix of an earlier week, or a count with no fix, shows as none)
    runs = streaks(rows)
    held: collections.Counter = collections.Counter()
    for x in runs:
        held[x["kind"]] += x["n"]
    return {"calls": dict(calls), "refused": dict(refused), "kinds": kinds, "senders": senders, "fixes": fixes, "bounces": bounces, "first": first,
            "streaks": collections.Counter(x["kind"] for x in runs), "streak_refusals": held, "messages": message_stats(rows, sent)}


def _share(refused: int, calls: int) -> str:
    return f"{refused / calls * 100:.1f}%" if calls else "n/a"


def _headline(t: dict[str, Any]) -> tuple[int, int]:
    return sum(t["refused"].get(x, 0) for x in HEADLINE), sum(t["calls"].get(x, 0) for x in HEADLINE)


def _message_lines(cur: dict[str, Any], prev: dict[str, Any], top: int) -> list[str]:
    """The report's lines on message calls (tally's "messages"): the calls and refusals with the week before, the calls the relay handled instead of refusing by kind, the refusals by kind, the streaks (one sender refused MSG_STREAK_MIN times or more on one target within MSG_STREAK_WINDOW, and how many of them are
    of the report's own rule, STREAK_MIN within STREAK_WINDOW), and the refusals sent again within RESEND_WINDOW. [] for a week with no message call."""
    m, p = cur.get("messages") or {}, prev.get("messages") or {}
    if not m.get("calls"):
        return []
    n, r = m["calls"], m["refused"]
    out = [f"- message calls: {r:,} of {n:,} refused ({_share(r, n)})" + (f"; the week before {p['refused']:,} of {p['calls']:,} ({_share(p['refused'], p['calls'])})" if p.get("calls") else "; no message calls the week before")]
    h = sum(m.get("handled", {}).values())
    if h:          # what the relay did instead of refusing, by the kind of refusal it replaced: these calls went through
        by_kind = collections.Counter()
        for (k, _how), v in m["handled"].items():
            by_kind[k] += v
        out.append(f"- message calls handled instead of refused (passed on, written onto an item or held, the sender told): {h:,} of {n:,} ({_share(h, n)}), " + " · ".join(f"{k} {v:,}" for k, v in by_kind.most_common(top)))
    if not r:
        return out
    shown = m["kinds"].most_common(top)
    out.append("- the kinds of message refusals: " + " · ".join(f"{k} {v:,} ({v / r * 100:.0f}%)" for k, v in shown)
               + (f" · {r - sum(v for _, v in shown):,} in other kinds" if r > sum(v for _, v in shown) else ""))
    if m["streaks"]:
        k = len(m["streaks"])
        out.append(f"- repeated message refusals (one sender refused {MSG_STREAK_MIN} times or more on one target, each within {MSG_STREAK_WINDOW // 60} minutes of the one before): {k:,} streak{'s' if k != 1 else ''} hold{'s' if k == 1 else ''} {m['streak_refusals']:,} of {r:,} refusals ({_share(m['streak_refusals'], r)}), "
                   f"{m['tight']:,} of them {STREAK_MIN} refusals or more within {STREAK_WINDOW // 60} minutes (" + " · ".join(f"{x['sender']} to {x['to']} {x['n']:,} ({x['kind']})" for x in m["streaks"][:top])
                   + (f" · {len(m['streaks']) - top:,} more" if len(m["streaks"]) > top else "") + ")")
    again = m["resent"]["same"] + m["resent"]["other"]
    if again:
        out.append(f"- message refusals sent again within {RESEND_WINDOW // 60} minutes (the same sender, a similar text): {again:,} of {r:,} ({_share(again, r)}), {m['resent']['same']:,} to the same target and {m['resent']['other']:,} to another")
    return out


def build(monday: dt.date, cur: dict[str, Any], prev: dict[str, Any], *, top: int = TOP_DEFAULT) -> str:
    """The report text of the week starting `monday`: the counts of that week (`cur`) and the week before (`prev`), from tally()."""
    r, n = _headline(cur)
    pr, pn = _headline(prev)
    sunday = monday + dt.timedelta(days=6)
    z = _cfg.tz()
    lines = [f"Refused board writes, {shown(monday)} to {shown(sunday)} ({_cfg.tz_abbr(dt.datetime.combine(monday, dt.time(12, 0)))}):"]
    lines.append(f"- create and update: {r:,} of {n:,} calls refused ({_share(r, n)})" + (f"; the week before {pr:,} of {pn:,} ({_share(pr, pn)})" if pn else "; no records for the week before"))
    if cur.get("streaks"):
        total, held, every = sum(cur["streaks"].values()), sum(cur["streak_refusals"].values()), sum(cur["refused"].values())
        before = f"; the week before {sum(prev['streaks'].values()):,} holding {sum(prev['streak_refusals'].values()):,} of {sum(prev['refused'].values()):,}" if prev.get("streaks") else ""
        lines.append(f"- repeated refusals (one writer refused {STREAK_MIN} times or more on one call within {STREAK_WINDOW // 60} minutes, a gap in the tool text): {total:,} streaks hold {held:,} of {every:,} refusals ({_share(held, every)}){before}"
                     + " (" + " · ".join(f"{k} {v:,} holding {cur['streak_refusals'][k]:,}" for k, v in cur["streaks"].most_common(top)) + ")")
    others = [(t, cur["refused"].get(t, 0), c) for t, c in sorted(cur["calls"].items()) if t not in HEADLINE and t != "message" and cur["refused"].get(t, 0)]          # message has its own lines below
    if others:
        lines.append("- other writes refused: " + " · ".join(f"{t} {x:,} of {c:,}" for t, x, c in others))
    lines += _message_lines(cur, prev, top)
    if r:
        lines.append("- the kinds of create and update refusals: " + " · ".join(f"{k} {v:,} ({v / r * 100:.0f}%)" for k, v in cur["kinds"].most_common(top)))
        rest = sum(cur["kinds"].values()) - sum(v for _, v in cur["kinds"].most_common(top))
        if rest > 0:
            lines[-1] += f" · {rest:,} in other kinds"
        lines.append("- refused most: " + " · ".join(f"{s} {v:,}" for s, v in cur["senders"].most_common(SENDERS_TOP)))
    if cur["fixes"]:
        total = sum(cur["fixes"].values())
        lines.append(f"- corrected by the server instead of refused: {total:,} (" + " · ".join(f"{k} {v:,}" for k, v in cur["fixes"].most_common()) + ")")
    if cur["bounces"] or prev["bounces"]:
        checked = lambda c: sum(v for k, v in c.items() if k in _cl.CHECKED)          # only a fix of a kind with a send-back check can be sent back: the share is of those, not of every fix
        sent_back, made = checked(cur["bounces"]), checked(cur["fixes"])
        before_back, before_made = checked(prev["bounces"]), checked(prev["fixes"])
        lines.append(f"- fixes the writer sent back: {sent_back:,} of the {made:,} fix{'' if made == 1 else 'es'} checked ({_share(sent_back, made)})" + (f"; the week before {before_back:,} of {before_made:,} ({_share(before_back, before_made)})" if before_made else "")
                     + (" (" + " · ".join(f"{k} {v:,}" + (f" of {cur['fixes'][k]:,}" if cur["fixes"].get(k) else "") for k, v in cur["bounces"].most_common()) + ")" if cur["bounces"] else ""))
    if cur.get("loops") or prev.get("loops"):
        lines.append(f"- wait loops found (items that wait on each other, told to their movers): {cur.get('loops', 0):,}; the week before {prev.get('loops', 0):,}")
    first = cur["first"]
    if first is not None and first > week_bounds(monday)[0] + 12 * 3600:
        lines.append(f"- the call log starts {shown(dt.datetime.fromtimestamp(first, z).date())}: the days before it are not counted")
    return "\n".join(lines)


def collect(monday: dt.date) -> tuple[dict[str, Any], dict[str, Any]]:
    a, b = week_bounds(monday)
    p, _ = week_bounds(monday - dt.timedelta(days=7))
    sent = delivered(p, b + RESEND_WINDOW)          # the delivered messages of both weeks and the hour after: a refusal at the end of a week is sent again after it
    cur, prev = tally(list(_cl.read(a, b)), sent), tally(list(_cl.read(p, a)), sent)
    from stackshot.audit import wait_loops as _loops  # noqa: PLC0415
    cur["loops"], prev["loops"] = _loops.log_count(a, b), _loops.log_count(p, a)      # rings of items that wait on each other, found by the minute walk
    return cur, prev


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


# ---------------------------------------------------------------------------------------------------------------- the daily analysis
RETRY_WINDOW = 600                       # seconds: a call by the same caller, on the same tool and item, this soon after a refusal of it is a retry
REPEAT_MIN = 3                           # a kind refused this many times or more in the day repeats
CHARS_PER_TOKEN = 4                      # the usual estimate: a token is about four characters
DAY_HOURS = 24
WEEK_DAYS = 7
NEEDS_FIX = "needs a fix (no hint yet)"
READS = ("get", "brief", "sessions", "anchors", "rules")          # the tools that only read: an error of one is a read error (route and bump_versions write)
READ_PREFIX = "read: "          # a read that errors is counted under its text with this before it
READ_HINT = "an error of a read, not a rule of the board: check the item id, project or name before reading, and read the list first when unsure."

# kind of refusal → the one line a caller is told to avoid it. The keys are the kind names of call_log.kind_of (a message refusal: "message: " and its kind slug). A repeating kind with no entry is listed as needing a fix.
HINTS: dict[str, str] = {
    "a step left out of next with no done or dropped": "keep every step the item had in next, or mark it done or dropped; read the item first and send the whole list.",
    "a description bullet over its limit": "keep each description bullet within its limit: the server splits a longer one only while the description stays within its line limit, so shorten bullets or cut facts.",
    "an outcome_text bullet over its limit": "keep each outcome_text bullet within its limit: the server splits a longer one only while the text stays within its line limit, so shorten bullets or cut facts.",
    "a description over its line limit": "cut the description to its line limit; move detail to the item's pages or its history.",
    "a description that does not open with its goal": "open the description with its goal as the first bullet.",
    "a changelog word in a description": "describe what the item is and where it lives, not what changed; changes belong in the status line.",
    "a line of next over its limit": "keep each line of next within its limit; one step per line.",
    "a subject over its limit": "shorten the subject to its limit; put detail in the description.",
    "a subject without a scope prefix": "start the subject with the scope prefix of the project.",
    "a wait with no end date": "give a wait on another item, an anchor, an event or news the user relays an end date: until=YYYY-MM-DD.",
    "a wait set without its reason": "send wait_reason with a wait you set on your own item.",
    "a wake in the wrong form": "write the wake as YYYY-MM-DDTHH:MM in the instance time.",
    "an item id in the wrong form": "write the item id as the board shows it, with its prefix and number.",
    "a hand-off with no check or date": "when you hand an item to another session, give the check or the date the hand-off is owed by.",
    "a front agent named as mover": "name a background agent as mover, never a front agent.",
    "a contact that is not a front agent": "contact= takes a front agent of the project, as the refusal lists them; leave it out to keep the project's own.",
    "a retired input": "this input is retired; read the tool text for the one that replaced it.",
    "no sender": "pass sender= with your own session name on every write.",
    "message: unknown-page-key": "address a session by name, or a project page as projects/<slug> spelled as the sessions or anchors listing shows it.",
    "message: message-too-long": "keep a message within its limit; put the long form on a page or in a file both sessions can read and send the pointer.",
    "an ask in the wrong form": "write the ask on one line as \"Decide: … · Recommend: … · Stakes: … · By: …\", every part with its label, at most 240 characters in all, a link's address counted.",
    "an ask with a second question in its Decide part": "ask one question and one decision per item, with one Decide and one Recommend part, neither split into several; another goes on an item of its own.",
    "an ask that approves a design or plan with no link in the ask": "link the design, plan or mockup inside the ask itself, as [words](url).",
    "an option without its label and line": "send 2 to 6 options as {label, line, recommended}: a label of at most 40 characters, a one-sentence line of at most 160, exactly one recommended.",
    "a said entry in the wrong form": "send said as a list of {tag, quote, msg} objects, msg being the uuid of the user's message in your transcript.",
    "a time wait with no recorded words or basis": "to check back on your own work send until and wait_reason with no wait_kind; a new park within the wait cap needs the user's words (said), and one past it takes said or a wait_basis.",
    "a date moved later with nothing else changed": "do not only move a date: in the same call mark a step done or dropped, write the next step or state the new reason.",
    "a date past the wait cap": "set a date within the wait cap; a later one needs the user's words (said) or a wait_basis that names a real date.",
    "a line of next that reads as a wait on a live item": "set the wait with until, after or wait_kind, and keep next to the action someone takes now.",
    "a wait with an input missing": "give the wait what its kind needs, as the refusal names it: until, wait_anchor, wait_event or after.",
    "a wait_basis the rule does not take": "write wait_basis as one line saying what happens, with its date as YYYY-MM-DD, on the day the wait ends or within 30 days after it; leave it out where the refusal says it is not needed.",
    "needs naming more than one mover": "name one mover in needs; who takes the item after an answer or a step goes in then=<session>.",
    "a reword of another session's step": "reword only a step your own session wrote; mark another's done or dropped, or ask its writer.",
    "an open item left with no open step": "keep one open step in next, opening with who takes it, or close the item.",
    "a close with a part missing": "send outcome, reason and outcome_text together in the closing call.",
    "a close reason over its limit": "keep the close reason within its limit; put the detail in outcome_text.",
    "a status state the work line does not have": "a work state is defined, assigned, in progress or done; a wait is set with until, after or wait_kind.",
    "clear_wait sent beside a new wait": "to change a wait send the new wait_kind without clear_wait, with a new value or \"none\" for a stored wait_anchor or wait_event; clear_wait alone ends the wait.",
    "an anchor park with no backstop date": "give a park that waits on an anchor a backstop, until=YYYY-MM-DD within the wait cap: the notice may never come.",
    "a wait_anchor that is not on the anchors list": "add the URL to the project's anchors list (the anchors tool, add=[url]) before naming it in wait_anchor.",
    "a wait_kind that is none of the kinds": "wait_kind is time, anchor, item, relay or event; a wait on someone outside is relay with wait_event, until and needs=[\"external\"].",
    "close fields on a write that is no close": "outcome, outcome_text, reason and superseded_by go only with a close: add status=\"completed\" or use the complete tool.",
    "a status that is not open or completed": "status is open or completed; a park is a date (until) with its wait fields, not a status.",
    "a close with a step still open": "mark each open step done or dropped in the closing update call (the complete tool takes no marks).",
    "a status line over its limit": "keep the work text to a few words within its limit; put the detail on the project page.",
    "a status line from a session the item does not name": "set work only on an item you move or whose needs names you; otherwise ask its mover to name you.",
    "a step over its limit": "keep step to a one-line summary within its limit; the actions go in lines of next that open with the user's name.",
    "a step to post a text with no draft": "when a step asks the user to post or send a text, put the exact text in draft= or link the document that holds it.",
    "a bare URL in a description, next or ask": "write a link in a description, next or ask as [words](url), never a bare address.",
    "the user left as mover with nothing to do": "an item the user moves needs something of theirs (step=, or needs=decision with an ask); otherwise name a session as mover.",
    "a park with nothing it waits for": "give a park what it waits for: until=YYYY-MM-DD, after=[<item>], a scoped anchor with a backstop date, or recycle=true; else set no park.",
    "an ask_by that is no date": "send until=YYYY-MM-DD, a day with no time of day; ask_by is its old name.",
    "anchors passed on an item write": "an item write takes no anchors: add them with anchors(project=<its project>, add=[url], items=[<its id>]).",
    "a front agent's date on handed-off work": "a front agent sets no date on work another session moves, whose close or hand-back reaches it; where no push does, pass watch_reason=<why>.",
    "options that are no list": "send options as a list of {label, line, recommended} objects; a string that is not that list written as JSON is refused.",
    "an alarming word in text the user reads": "use the everyday word the refusal names, and put file names, commands and code in backticks.",
    "another mover on an item that is the user's": "on an item of the user's leave mover out and name the session that takes it next in then=<session>.",
    "message: session-id-use-name": "address a running pane by its name, not by the transcript id of a session that has ended.",
    "message: no-receiver": "a retired session, or one with no pane, takes no message: send to the project page the refusal names, or put it on the item it concerns.",
    "message: dead-recipient": "read the sessions listing before sending: address a running pane by its name, or a project page as projects/<slug>.",
    "message: mark-not-first-line": "to a front agent, put the mark for the user on the first line only when the user has something to do; send anything else where the refusal says.",
    "message: no-action-note-from-builder": "send a front agent no done, taken or no-action note: write it on the item it concerns, or say nothing.",
    "message: no-action-note": "send a front agent no done, taken or no-action note: write it on the item it concerns, or say nothing.",
    "message: unmarked-not-for-owner": "send what asks nothing of the user to the project's background agent or page, not to a front agent.",
    "message: marked-no-action-phrase": "mark a message for the user only when the user has something to do; put a report on the item it concerns.",
    "message: marked-no-item-of-his": "in a message marked for the user, name by its plain id an open item that waits on the user (needs=decision with an ask, or the user's step).",
    "message: marked-no-turn": "a front agent takes a turn only for what the user talks to it about or asked to be told: put it on the item, or send it to the agent the refusal names.",
    "message: no-sender": "pass sender= with your own session name or id on every message.",
    "message: no-target": "pass to= with the session's name or id, or a project page as projects/<slug>.",
    "message: empty-message": "send the message's text; a call with none is refused.",
    "message: question-from-owner": "leave question= out of a message sent as the user: only a front agent marks a question.",
    "message: question-with-fyi": "send question=true or fyi=true, never both.",
    "message: no-session": "address a running pane by the name the sessions listing shows, a cloud session by its cse_ id, or a project page as projects/<slug>.",
    "message: unknown-transcript-id": "address a pane by its name, or a cloud session by its cse_ id; a transcript id reaches only a pane some machine reports.",
    "message: front-not-held": "what asks nothing of the user does not go to a front agent: put it on the item it concerns, or send it to the project page.",
    "message: script-fyi-not-held": "a script sends an fyi to the project page (projects/<slug>) when the front agent cannot hold it.",
}

# kind of refusal with no hint, and why none fits: a repeating one is listed with this line, and asks for nothing.
NO_HINT: dict[str, str] = {
    "message: not recorded": "no hint fits: lines logged before the log kept a message refusal's kind, so there is no one fault to name.",
    "message: unclassified": "no hint fits: an error from outside the relay's own rules, so there is no one fault to name; read the logged refusals.",
    "message: retired-recipient": "no hint fits: the relay sends such a message on to the project page itself, so the caller has nothing to change.",
    "message: no-keeper": "no hint fits: the page has no agent that can take a message, a gap in the instance's setup and not in the call.",
    "message: delivery-failed": "no hint fits: the call passed every rule and the push to the session failed; the logged refusal carries the push error.",
}


def _kind_of_row(r: dict[str, Any]) -> str:
    """The kind a refused line is counted under in the daily analysis: a message by its kind slug (NO_KIND for a line from before kinds were logged), any other tool's refusal by the refusal's text (call_log.kind_of)."""
    tool = str(r.get("tool") or "")
    if tool == "message":
        return "message: " + (str(r.get("kind") or "") or NO_KIND)
    if tool in READS:          # a read that errors (no such item, a bad argument) is no rule of the board: its own kinds, with one hint for them all
        return READ_PREFIX + _kind_of_why(str(r.get("why") or ""))
    return _kind_of_why(str(r.get("why") or ""))


def _refusal_chars(r: dict[str, Any]) -> int:
    """The length of a refusal's text: the whole length the log kept (`rlen`), else the clipped text of a line from before it was kept."""
    v = r.get("rlen")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if not math.isfinite(v):          # Infinity or NaN in a line: a size that is none (it never aborts the analysis)
            return 0
        if v >= 0:
            return int(v)
    return len(str(r.get("why") or ""))


def _request_chars(r: dict[str, Any]) -> int:
    v = r.get("req")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 else 0          # a line from before sizes were kept is a call of unknown size: it counts as none


def _issues_letter() -> str:
    """The store letter of issue-numbered items ([github] issues_letter, default g): the letter a bare board id is stored under."""
    try:
        from stackshot.github import ghsync as _gh  # noqa: PLC0415
        return _gh.letter()
    except Exception:  # noqa: BLE001
        return "g"


def _item_key(v: Any) -> str:
    """An item as one key however it was written: `board#N`, `#N`, `N` and the store id (the issues letter and N) are the same item (a refused call keeps the item as the caller sent it, a call that went through the store's id)."""
    t = str(v or "").strip().lower()
    m = re.fullmatch(r"(?:board)?#?(\d+)", t)
    if m:
        return f"{_issues_letter()}{m.group(1)}"
    m = re.fullmatch(r"([a-z])(\d+)", t)
    return f"{m.group(1)}{m.group(2)}" if m else t


def _target(r: dict[str, Any]) -> str:
    """What a call is about, for matching a retry: a message by its target session or page, a create by nothing (a refused create has no item, and its digest changes when the subject is corrected: sender and tool tell it), any other call by its item."""
    tool = str(r.get("tool") or "")
    if tool == "create":
        return "*"
    if tool == "message":
        return _fold(r.get("to"))
    return _item_key(r.get("item"))


def retries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The lines that are retries: a call by the same caller (sender) of the same tool on the same target (`_target`) that comes within RETRY_WINDOW after a refusal of that call, went through or refused; each refusal is retried once (a call that goes
    through ends the chain, a retry that is refused again anchors the next). A refusal with no caller (a write refused for naming none) is retried by a call that names one. A line with no caller of its own, or no target, is no call to match."""
    out: list[dict[str, Any]] = []
    # the refusals not yet retried, by (tool, target, sender): each bucket is in time order, so its newest entry is its last; an entry older than RETRY_WINDOW is never matched again (rows are read in time order), and a bucket drops its expired front as it is looked at
    open_: dict[tuple[str, str, str], collections.deque[tuple[int, dict[str, Any]]]] = collections.defaultdict(collections.deque)
    for seq, r in enumerate(sorted(rows, key=lambda r: r["t"])):
        tool, who, target = str(r.get("tool") or ""), str(r.get("sender") or ""), _target(r)
        if who and target:
            best: collections.deque[tuple[int, dict[str, Any]]] | None = None
            for s in {"", who}:          # a refusal with no caller is retried by any call that names one; a refusal with a caller only by that caller
                q = open_.get((tool, target, s))
                while q and r["t"] - q[0][1]["t"] > RETRY_WINDOW:
                    q.popleft()
                if q and (best is None or q[-1][0] > best[-1][0]):
                    best = q
            if best is not None:
                best.pop()
                out.append(r)
        if r.get("ok") is False and target:
            open_[(tool, target, who)].append((seq, r))
    return out


def daily_tally(rows: list[dict[str, Any]], again: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts of one window of call lines (every tool): {"calls", "refused", "tools": Counter of refusals by tool, "kinds": Counter by kind (`_kind_of_row`), "senders": Counter by caller,
    "retries": the retries among `again` that fall inside the window's lines, "retry_chars": their request sizes, "refusal_chars": the refusals' text sizes}. `again` is `retries()` of a longer span, so a retry whose refusal came before the window still counts."""
    tools: collections.Counter = collections.Counter()
    kinds: collections.Counter = collections.Counter()
    senders: collections.Counter = collections.Counter()
    refused = rchars = 0
    for r in rows:
        if r.get("ok") is False:
            refused += 1
            tools[str(r.get("tool") or "?")] += 1
            kinds[_kind_of_row(r)] += 1
            senders[str(r.get("sender") or "-")] += 1
            rchars += _refusal_chars(r)
    ids = {id(r) for r in rows}
    mine = [r for r in again if id(r) in ids]
    return {"calls": len(rows), "refused": refused, "tools": tools, "kinds": kinds, "senders": senders,
            "retries": len(mine), "retry_chars": sum(_request_chars(r) for r in mine), "refusal_chars": rchars}


def collect_daily(now: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """(the last 24 hours, the last 7 days) up to `now`, each from daily_tally."""
    since = now - WEEK_DAYS * 86400
    rows = list(_cl.read(since, now + 1))
    again = retries(rows)
    cut = now - DAY_HOURS * 3600
    return daily_tally([r for r in rows if r["t"] >= cut], again), daily_tally(rows, again)


def _tokens(t: dict[str, Any]) -> int:
    return round((t["refusal_chars"] + t["retry_chars"]) / CHARS_PER_TOKEN)


def repeating(day: dict[str, Any]) -> list[tuple[str, int, str]]:
    """The kinds refused REPEAT_MIN times or more in the day → [(kind, n, hint or NEEDS_FIX)], the most refused first."""
    return [(k, v, READ_HINT if k.startswith(READ_PREFIX) else HINTS.get(k) or NO_HINT.get(k, NEEDS_FIX)) for k, v in day["kinds"].most_common() if v >= REPEAT_MIN]


def build_daily(now: float, day: dict[str, Any], week: dict[str, Any], *, top: int = TOP_DEFAULT) -> str:
    """The daily analysis text: the last 24 hours and the last 7 days up to `now`: calls and refusals, refusals by tool, by rule kind and by caller session, the retries, the tokens of refusal text and retried requests (characters / CHARS_PER_TOKEN: an estimate),
    and the kinds that repeat in the day with the one-line hint for each, or "needs a fix"."""
    at = dt.datetime.fromtimestamp(now, _cfg.tz())
    both = (("24h", day), ("7d", week))
    lines = [f"Refusals and retries of board tool calls, the last {DAY_HOURS} hours and the last {WEEK_DAYS} days up to {shown(at.date())} {at:%H:%M} ({_cfg.tz_abbr(at.replace(tzinfo=None))}):"]
    lines.append("- calls refused of all calls (every tool, a read that errors counts as refused): " + " · ".join(f"{n} {w['refused']:,} of {w['calls']:,} ({_share(w['refused'], w['calls'])})" for n, w in both))
    for label, key in (("tool", "tools"), ("rule kind", "kinds"), ("caller session", "senders")):
        for n, w in both:
            c = w[key]
            lines.append(f"- refusals per {label}, {n}: " + (" · ".join(f"{k} {v:,}" for k, v in c.most_common(top)) + (f" · {sum(c.values()) - sum(v for _, v in c.most_common(top)):,} in others" if len(c) > top else "") if c else "none"))
    lines.append(f"- retries (the same caller on the same tool and item within {RETRY_WINDOW // 60} minutes after a refusal): " + " · ".join(f"{n} {w['retries']:,} ({w['retry_chars']:,} request characters)" for n, w in both))
    lines.append(f"- tokens spent on refusals and retries (estimate, characters / {CHARS_PER_TOKEN}: refusal text plus retried requests): " + " · ".join(f"{n} {_tokens(w):,} ({w['refusal_chars']:,} refusal characters + {w['retry_chars']:,} retried request characters)" for n, w in both))
    rep = repeating(day)
    if rep:
        lines.append(f"- kinds refused {REPEAT_MIN} times or more in the last {DAY_HOURS} hours (each wants a same-day fix or hint):")
        lines += [f"  - {k} {v:,}: {h}" for k, v, h in rep[:top]]
        if len(rep) > top:
            lines.append(f"  - and {len(rep) - top:,} more kinds repeat (the kinds per rule above list the most refused)")
    else:
        lines.append(f"- no kind was refused {REPEAT_MIN} times or more in the last {DAY_HOURS} hours")
    return "\n".join(lines)


Deliver = Callable[[str, str, str], tuple[bool, str]]
Resolve = Callable[[str], str]

ASK = ("\n\nWhat I ask of you: take the repeated-refusal kinds first (a writer refused again and again on one call: the tool text leaves something out, so a hint at write time or a clearer line "
       "of tool text closes it). Then, for each kind above that repeats, file a write-time hint or a server fix for it (a refusal whose intent the server can read and put right, with one plain line "
       "to the writer saying what it did), or say in a line why none fits; a kind already filed needs nothing. A fix the writers send back is worse than a plain refusal: look at those next.")


def deliver_client(to: str, text: str, sender: str) -> tuple[bool, str]:
    """One message that asks nothing (fyi) through client.py (this box's token) → (delivered, the server's answer)."""
    from stackshot.fleet import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, sender, fyi=True)
    return status == 200, f"[{status}] {said}"


def deliver_agent_client(to: str, text: str, sender: str) -> tuple[bool, str]:
    """One normal message (it asks something of its reader) through client.py → (delivered, the server's answer)."""
    from stackshot.fleet import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, sender)
    return status == 200, f"[{status}] {said}"


def background_agent(to: str) -> str:
    """The background agent of the project page `to` that reads the report: the first of anchors.background_ranked (the builder, else the others); "" for a name that is no page key, a project with none, or a registry that cannot be read."""
    if "/" not in to:
        return ""
    try:
        from stackshot.anchors import anchors as _anc  # noqa: PLC0415 — the registry is read only when a report is sent
        ranked = _anc.background_ranked(to)
    except Exception:  # noqa: BLE001
        return ""
    return ranked[0][2] if ranked else ""


def run(*, dry: bool = False, force: bool = False, week: dt.date | None = None, now: float | None = None, cfg: dict[str, Any] | None = None,
        deliver: Deliver = deliver_client, state: Path | None = None, deliver_agent: Deliver = deliver_agent_client, resolve: Resolve = background_agent) -> dict[str, Any]:
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
    agent = resolve(cfg["to"])
    also = ""
    if agent:                      # the page copy is out; the background agent gets the same report as a message that asks it to file the repeating kinds. Its failure does not unsend the page copy or the record
        ok2, said2 = deliver_agent(agent, text + ASK, cfg["sender"])
        also = f" and to its background agent {agent}" if ok2 else f"; the message to its background agent {agent} failed: {said2}"
    done["weeks"] = sorted({*done["weeks"], key})[-60:]
    try:
        _write_sent(sp, done)
    except OSError as e:          # the report is out: a record that cannot be written is reported as such, not raised as a failed send
        return {"week": monday, "text": text, "sent": True, "why": f"sent to {cfg['to']}{also}, but not recorded ({e}): the next run will send it again until the record can be written"}
    return {"week": monday, "text": text, "sent": True, "why": f"sent to {cfg['to']}{also}"}


ASK_DAILY = ("\n\nWhat I ask of you: the kinds marked 'needs a fix' repeat today and have no hint for the writers yet: file a write-time hint or a server fix for each, add its line to the hint table "
             "(tools/refusal_report.py HINTS), or say in a line why none fits (NO_HINT there).")


def run_daily(*, dry: bool = False, force: bool = False, now: float | None = None, cfg: dict[str, Any] | None = None, deliver: Deliver = deliver_client,
              state: Path | None = None, deliver_agent: Deliver = deliver_agent_client, resolve: Resolve = background_agent) -> dict[str, Any]:
    """→ {"day": the date, "text": the analysis, "sent": bool, "why": what happened}. The daily analysis of the last 24 hours and 7 days, sent once per calendar day (the first run of the day: the audit unit's 05:00 run) to the place the weekly
    report goes ([refusal_report] to, as a message that asks nothing), and to the project's background agent too when a repeating kind has no hint. A day with no refusal in the last 24 hours sends nothing. Gated by [refusal_report] enabled like the weekly one;
    the record of the days sent is the `days` list of the same sent.json."""
    cfg = cfg or settings()
    at = time.time() if now is None else now
    today = dt.datetime.fromtimestamp(at, _cfg.tz()).date()
    sp = state or state_file()
    done = _read_sent(sp)
    key = today.isoformat()
    if key in done.get("days", []) and not force and not dry:
        return {"day": today, "text": "", "sent": False, "why": "already sent"}
    day, week = collect_daily(at)
    if not dry:
        _cl.prune(at)          # the call log keeps the current month and the 12 before it (call_log.KEEP_MONTHS); never raises
    if not day["refused"]:
        return {"day": today, "text": "", "sent": False, "why": "no refusals in the last 24 hours"}
    text = build_daily(at, day, week, top=cfg["top"])
    if dry:
        return {"day": today, "text": text, "sent": False, "why": "dry run"}
    if not cfg["enabled"]:
        return {"day": today, "text": text, "sent": False, "why": "not enabled ([refusal_report] enabled)"}
    ok, said = deliver(cfg["to"], text, cfg["sender"])
    if not ok:
        return {"day": today, "text": text, "sent": False, "why": said}
    also = ""
    agent = resolve(cfg["to"]) if any(h == NEEDS_FIX for _, _, h in repeating(day)) else ""
    if agent:
        ok2, said2 = deliver_agent(agent, text + ASK_DAILY, cfg["sender"])
        also = f" and to its background agent {agent}" if ok2 else f"; the message to its background agent {agent} failed: {said2}"
    done["days"] = sorted({*done.get("days", []), key})[-60:]
    try:
        _write_sent(sp, done)
    except OSError as e:
        return {"day": today, "text": text, "sent": True, "why": f"sent to {cfg['to']}{also}, but not recorded ({e}): the next run will send it again until the record can be written"}
    return {"day": today, "text": text, "sent": True, "why": f"sent to {cfg['to']}{also}"}


def main_daily(dry: bool, force: bool) -> int:
    res = run_daily(dry=dry, force=force)
    if res["text"]:
        print(res["text"])
    print(f"refusal report (daily): {res['why']} ({res['day']})")
    return 0 if res["sent"] or res["why"] in ("dry run", "already sent", "no refusals in the last 24 hours") or res["why"].startswith("not enabled") else 1


def main(argv: list[str]) -> int:
    a = list(argv)
    if a and a[0] == "run":
        a = a[1:]
    only_daily = bool(a) and a[0] == "daily"
    if only_daily:
        a = a[1:]
    dry, force, week = False, False, None
    while a:
        k = a.pop(0)
        if k == "--dry-run":
            dry = True
        elif k == "--force":
            force = True
        elif k == "--week" and a and not only_daily:
            try:
                week = dt.date.fromisoformat(a.pop(0))
            except ValueError:
                print("refusal report: --week takes a date, YYYY-MM-DD", file=sys.stderr)
                return 2
        else:
            print("usage: refusal_report.py run [--dry-run] [--force] [--week YYYY-MM-DD]   |   refusal_report.py daily [--dry-run] [--force]", file=sys.stderr)
            return 2
    if only_daily:
        return main_daily(dry, force)
    res = run(dry=dry, force=force, week=week)
    if res["text"]:
        print(res["text"])
    print(f"refusal report: {res['why']}" + (f" (week of {res['week']})" if res.get("week") else ""))
    rc = 0 if res["sent"] or res["why"] in ("dry run", "already sent", "no call records for the week") or res["why"].startswith("not enabled") else 1
    if week is not None:          # a week asked for by name is the weekly report alone
        return rc
    print()
    rc_daily = main_daily(dry, force)          # the daily analysis follows the weekly count in the same run, each sent once (the audit's 05:00 run sends it; its 20:00 run finds it sent)
    return rc or rc_daily


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
