"""tools/refusal_report.py — the weekly count of board writes the server refused.

Reads the call log the server keeps (call_log.py: one line per create, update, complete, confirm and message call, went through or refused, in
`<paths.state>/calls/<YYYY-MM>.jsonl`) and reports, for one calendar week Monday to Sunday in the instance timezone: how many create and update calls
were refused of how many, the share, the week before it, the kinds of refusal that make most of them, the sessions that were refused most, and what the
server corrected instead of refusing (a bare item number or #N in any call that takes an item id, a close included, read as board#N, a message's page key spelled another way, a wake with seconds or an offset, a subject with no scope prefix, a long description or outcome_text bullet split at its sentence ends or, for one clause, at a comma, colon, dash or parenthesis, or, with no such cut, cut at a space onto an indented line under it (bullet-wrap),
a step left out of next kept open, a subject or a status line cut at its last word that fits, an ask-by with a time of day cut to its day, a bare address in a description written as a link, the server's own fixes of a wait), and how many of those fixes the writer sent back (call_log.bounces; of the fixes of the kinds that have the check, call_log.CHECKED), and the streaks: one writer refused STREAK_MIN (3) times or more on one call (the same tool and item) with each refusal within STREAK_WINDOW (15 minutes) of the one before, counted by kind and listed first, since a streak marks a gap in the tool text. Message calls have lines of their own (the message tool and the client route's script messages, `_message_lines`): the calls refused of all with the week before, the refusals by the kind slug the call log keeps (`service/messaging.py` `Refused`; `not recorded` for a line from before kinds were logged), the streaks of one sender refused MSG_STREAK_MIN (2) times or more on one target within MSG_STREAK_WINDOW (an hour) of the one before, how many of them also meet the rule above (3 within 15 minutes), and the refusals sent again within RESEND_WINDOW (an hour) with a similar text by the same sender (`similar`: difflib ratio of at least SIMILAR, 0.5), to the same target or another, looked for in the later refusals and in the delivered messages of the message log (`messages.jsonl`, `delivered`). One more line, when the week or the one before it had any: the wait loops the minute walk found (audit/wait_loops.py: items that wait on each other), counted from its log. Tokenless: no model call.

    refusal_report.py run [--dry-run] [--force] [--week YYYY-MM-DD]
    audit.py refusals [--dry-run] [--force] [--week YYYY-MM-DD]       the same, from the audit's own entry point (the timer's unit runs it after the audit run)

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
import os
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
                kinds = [_cl.kind_of(str(x.get("why") or "")) for x in run_]
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
