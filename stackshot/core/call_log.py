"""call_log.py — the count of board calls the server refused, and the small corrections it made instead of refusing.

The server writes one line per call of every tool (the counted writes create, update, complete, confirm and message, and every other tool, a read too) to `<paths.state>/calls/<YYYY-MM>.jsonl`:

    {"t": epoch seconds, "tool": "update", "ok": true}                                          the call went through
    {"t": …, "tool": "update", "ok": true, "fix": ["wake", "item-id"]}                           it went through after the server corrected a field itself (see `fixed`)
    {"t": …, "tool": "update", "ok": false, "item": "board#N", "sender": "my-x", "why": "…"}    the server refused it (the ToolError's text, whitespace folded, clipped)

`tools/refusal_report.py` reads these lines for its weekly report (the five writes) and its daily analysis (every tool). What a line holds of a call: the tool, the caller (`sender`, when the call passed one), ok or refused, the sizes (`req`, `rlen`), the item only when it is an id,
and for a refusal its text with the arguments it quotes removed (an anchors refusal also loses any quoted or mailbox-looking part), clipped. The call's other arguments are never logged: a description, a draft, a project, a session name or a said line stays out. The one exception is a refused message call, which also keeps
what it was about, so refusals can be told apart later (the message tool's text is a record its sender may want back, and a refusal leaves no other copy of it):

    {"t": …, "tool": "message", "ok": false, "item": "", "sender": "my-x", "why": "…", "to": "other-y", "kind": "marked-no-turn", "text": "…"}      to: the target as the sender wrote it; kind: the refusal site's slug (service/messaging.py `Refused`); text: the message as a delivered row keeps it, clipped to TEXT_MAX

    {"t": …, "tool": "update", "ok": true, "bounce": ["wake_park"]}                             it went through and the writer sent a fix of the server's back (see `bounces`)

A message call the relay handled in another way than the sender asked, where it once refused (service/messaging.py `_handled`: passed to the project's background agent, written onto the item it names, held for the front agent's next turn),
goes through as a line that keeps the refusal site's kind and says so, so the weekly count can show it as handled and not as refused:

    {"t": …, "tool": "message", "ok": true, "item": "", "sender": "my-x", "to": "other-y", "kind": "unmarked-not-for-owner", "outcome": "handled", "how": "passed-on"}

A reply that tells its writer something to look at, with nothing corrected and nothing refused (`noted`: an update changed the words of the Goal sentence and left the subject), keeps its kind apart from the fixes:

    {"t": …, "tool": "update", "ok": true, "note": ["goal-moved"], "item": "board#N", "sender": "my-x"}

Every other tool's call (get, brief, sessions, anchors, rules, route …) is logged the same way, and a read that errors is logged as refused. Every line the server writes also carries the sizes that let the daily analysis
(tools/refusal_report.py `daily`) put a token estimate on refusals and retries, and no content:

    {"t": …, "tool": "get", "ok": true, "item": "board#N", "sender": "my-x", "req": 24}                         req: the call's arguments as sent, in characters (item and sender only when the call had them)
    {"t": …, "tool": "update", "ok": false, …, "why": "…", "req": 812, "rlen": 1450}                         rlen: the refusal's whole text in characters (`why` is clipped to WHY_MAX)

A line written before these fields existed has neither: it reads as a call of unknown size.

A correction (`fixed`) is a pure fact the server can put right without a judgment: a bare item number read as the board id, a wake with seconds or a UTC offset read as the
instance time, a subject with no scope prefix given the one its project's scope names. The server stores the corrected field, adds one line to the reply saying what it did
(`reply_note`), and counts it here. A mover who disagrees sends the field again as they want it and the server leaves it alone.

Stdlib only; the config is read through config.py at each use."""
from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from stackshot.core import config as _cfg
from stackshot.core.lines import MSG_MAX, newline_lines

COUNTED = ("create", "update", "complete", "confirm", "message")      # the write tools whose calls get a correction pass and are counted in the weekly report (every other tool's calls are logged too: see `record`)
TOOL_MAX = 30                                                         # characters of a tool's name kept
WHY_MAX = 300                                                         # characters of a refusal's text kept
TEXT_MAX = MSG_MAX                                                    # characters of a refused message's text kept: the message tool's own limit, so a message it takes is kept whole
TO_MAX = 80                                                           # characters of a refused message's target kept

BOUNCE = "bounce:"            # a fix kind written as BOUNCE + kind is a bounce-back, not a fix (`bounced`)
HANDLED = "handled:"          # a fix kind written as HANDLED + refusal kind + ":" + how is a message the relay handled where it once refused (`handled`): it is no fix and has no line in the reply
HOW_MAX = 40                  # characters of the `how` of a handled message kept
NOTE = "note:"                # a fix kind written as NOTE + kind is a line a reply gave its writer with nothing corrected (`noted`): it is no fix, and the line is the reply's own
NO_RESEND = frozenset({"item-id", "description-bullet", "outcome-bullet", "bullet-wrap", "outcome-wrap", "step-none", "his-step-settled", "step-none-applied", "said-text", "step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url", "wait-basis-dropped", "description-goal", "step-split", "step-split-dropped", "step-reworded", "outcome-superseded"})   # fixes whose reply line does not invite a resend: the field sent again as written would be refused, fixed the same, change nothing, or be settled the same way (each line says how to change it)

_FIXES: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar("call_log_fixes", default=None)
_DETAIL: contextvars.ContextVar[dict[str, dict[str, Any]] | None] = contextvars.ContextVar("call_log_detail", default=None)
_LOCK = threading.Lock()
OPEN_WINDOW = 3600.0            # a fix is open to a bounce-back for this long: the writer's next move on the item (a later write after it is no reaction to the fix)
OPEN_KEEP = 100                 # fixes kept open for one writer at once (that writer's oldest go first: another writer's fixes never push one out)
OPEN_TOTAL = 2000               # fixes kept open in all (the oldest go first): the bound of the file, however many writers there are
NO_RESEND |= {"status-closed", "work-waiting"}      # two words read as the one the tool takes (a close's status, a status line's state): sent again they are read the same, and no later write tells a send-back


def begin() -> "tuple[contextvars.Token[list[tuple[str, str]] | None], contextvars.Token[dict[str, dict[str, Any]] | None]]":
    """Start collecting the corrections of one tool call (the middleware calls this before the tool runs)."""
    return _FIXES.set([]), _DETAIL.set({})


def end_detail(token: Any) -> tuple[list[tuple[str, str]], dict[str, dict[str, Any]]]:
    """Stop collecting → (the corrections the call made, [(kind, the line that tells it)] in order, each kind once; the detail each kind left for the bounce-back check, by kind)."""
    got = _FIXES.get() or []
    detail = _DETAIL.get() or {}
    _FIXES.reset(token[0])
    _DETAIL.reset(token[1])
    seen: set[str] = set()
    return [(k, n) for k, n in got if not (k in seen or seen.add(k))], detail


def end(token: Any) -> list[tuple[str, str]]:
    """Stop collecting → the corrections the call made, [(kind, the line that tells it)] in order, each kind once."""
    return end_detail(token)[0]


def _h(text: Any) -> str:
    return hashlib.sha1(" ".join(str(text or "").split()).encode("utf-8")).hexdigest()[:16]


def fixed(kind: str, note: str, **detail: Any) -> None:
    """The server corrected a field of the call that is running (no call running: nothing is recorded, as for a stored value read at a start). `detail` is what the bounce-back check needs
    (see `undone`): `fields` (the arguments that write the corrected field), `stored` (the value the server stored), `sent` (the value as the writer sent it), `token`: the last three are kept as digests, never as text."""
    got = _FIXES.get()
    if got is not None:
        got.append((kind, note))
        d = _DETAIL.get()
        if d is not None and detail and kind not in d:
            d[kind] = {k: (_h(v) if k in ("stored", "sent", "token") else v) for k, v in detail.items()}


def unfix(kind: str) -> str:
    """Take back a correction the running call noted and then did not need (a write made again without it) → the line that told it, "" when none was noted."""
    got = _FIXES.get()
    gone = next((n for k, n in got or [] if k == kind), "")
    if got is not None:
        got[:] = [(k, n) for k, n in got if k != kind]
    if (d := _DETAIL.get()) is not None:
        d.pop(kind, None)
    return gone


def mark() -> int:
    """How many corrections the running call has noted so far (for `rewind`)."""
    return len(_FIXES.get() or [])


def rewind(n: int) -> None:
    """Take back every correction noted since `mark()` gave `n`: a call refused for its faults corrected nothing (the checks that ran on past a fault, to name every fault at once, may have noted fixes for a write that was not made)."""
    got = _FIXES.get()
    if got is None or len(got) <= n:
        return
    del got[n:]
    if (d := _DETAIL.get()) is not None:
        for k in [k for k in d if not any(kk == k for kk, _ in got)]:
            d.pop(k)


def counted(kind: str, **detail: Any) -> None:
    """A fix of the server's own kind (server_fixes.record) whose reply already tells it in its own words: counted in the log, no line added to the reply."""
    fixed(kind, "", **detail)


def noted(kind: str) -> None:
    """The reply of the call that is running tells its writer something to look at, with nothing corrected and nothing refused: counted in the log under `note`, never as a fix, and no line is added to the reply (the caller wrote its own).
    No call running: nothing is recorded."""
    fixed(NOTE + kind, "")


def handled(kind: str, how: str) -> None:
    """The relay handled the message call that is running another way than the sender asked, where it once refused it with `kind` (service/messaging.py `Refused.kind`): `how` says in a word or two what it did (`passed-on`,
    `written-on-item`, `held`, `judged-on-items`). The call is logged as one that went through, keeping the kind and `outcome: handled` (`record`), so the weekly count shows it as handled and not as refused. No call running: nothing is recorded."""
    fixed(f"{HANDLED}{kind}:{how}", "")


def handled_of(fixes: list[tuple[str, str]] | None) -> tuple[str, str]:
    """(kind, how) of the first handled message among a call's fixes (`handled`), ("", "") when there is none."""
    for k, _ in fixes or []:
        if k.startswith(HANDLED):
            kind, _, how = k[len(HANDLED):].partition(":")
            return kind, how
    return "", ""


# ---------------------------------------------------------------------------------------------------------------- bounce-backs: the writer undoes or redoes what the server did
# A bounce-back is the writer reacting to a fix it was told about: a later write by the same writer, on the same item, within OPEN_WINDOW, that undoes the fix or writes the fixed field again as it wants it.
# A plain retry after a refusal is none (nothing was fixed). The middleware keeps each fix that has a check open (`remember`) and asks of each later write by that writer on that item whether it undid one (`bounces`).
# The check per kind is cheap and reads only the later call's arguments against what the fix left:
#   wake, subject-prefix, description-bullet, outcome-bullet, bullet-wrap, outcome-wrap, subject-cut, description-url   the later call writes the same field with a value other than the one the server stored and the one the writer sent first (the same text again is no send-back)
#   wake_park                                  the later call sends clear_hold or clear_wake, or a wake other than the parked one
#   wait_reason                                the later call sends a wait_basis, clear_wait_basis, clear_hold or clear_wake
#   front_mover                                the later call names the front agent again in the field the server substituted
# Not checked, because nothing the writer sends later can tell: item-id (the item meant is the item written), step-none (the server changed nothing), his-step-settled, step-none-applied and said-text (the writer's retry is no undoing: it is the same write settled again, or the same said), step-split, step-split-dropped and step-reworded (the writer sent the long text as it was; sent again it is split the same way, and a later write of the lines is what the writer wants), step-kept (the writer's later mark or reword is no send-back: it is what the line asks for), work-cut and ask-by-day (a shorter line or another day is the intended next write), wait-basis-dropped (the basis sent again is dropped again: nothing a later write sends tells a send-back), description-goal (the label sent as it was is relabelled again; a later description is an edit, not an undoing), settled_pick (a reading, not a write), and the fixes the
# audit's passes make (no writer, so no fix is counted either; their send-back stays in metadata.fix_declined). A write that began before the fix was made could not have read its note: it is no bounce-back.
# What open-fixes.json holds: per writer and item, the kind, the time, and digests (never text) of the value stored and sent; a writer's name is a digest in the key. It errs low by design: a record
# goes after an hour, past OPEN_KEEP for one writer or past OPEN_TOTAL in all.
CHECKED = ("wake", "subject-prefix", "description-bullet", "outcome-bullet", "bullet-wrap", "outcome-wrap", "subject-cut", "description-url", "wake_park", "wait_reason", "front_mover")


def _arg(a: dict[str, Any], k: str) -> str:
    v = a.get(k)
    return v.strip() if isinstance(v, str) else ""


def undone(kind: str, d: dict[str, Any], a: dict[str, Any]) -> bool:
    """Does a later call with arguments `a` undo or redo the fix `kind` that left `d` (the detail `fixed` was given: its stored, sent and token are digests)?"""
    if kind in ("wake", "subject-prefix", "description-bullet", "outcome-bullet", "bullet-wrap", "outcome-wrap", "subject-cut", "description-url"):
        for f in d.get("fields") or []:
            v = _arg(a, f)
            if v and _h(v) != d.get("stored") and _h(v) != d.get("sent"):
                return True
        return False
    if kind == "wake_park":
        w = _arg(a, "wake")
        return bool(a.get("clear_hold") or a.get("clear_wake")) or (w != "" and _h(w) != d.get("stored"))
    if kind == "wait_reason":
        return bool(_arg(a, "wait_basis") or a.get("clear_wait_basis") or a.get("clear_hold") or a.get("clear_wake"))
    if kind == "front_mover":
        return any(_arg(a, f) != "" and _h(_arg(a, f).lower()) == d.get("stored") for f in d.get("fields") or [])
    return False


def _open_file() -> Path:
    return _cfg.state("calls") / "open-fixes.json"


def _read_open() -> dict[str, list[dict[str, Any]]]:
    try:
        d = json.loads(_open_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _trim(d: dict[str, list[dict[str, Any]]], limit: int, group: Any) -> dict[str, list[dict[str, Any]]]:
    """`d` with at most `limit` entries in each group (`group(key)`), the oldest of a group over it dropped."""
    seen: dict[str, list[tuple[float, str]]] = {}
    for k, v in d.items():
        for e in v:
            seen.setdefault(group(k), []).append((e.get("t", 0), k))
    for g, got in seen.items():
        if len(got) > limit:
            for _, k in sorted(got)[: len(got) - limit]:
                d[k] = d[k][1:]
    return {k: v for k, v in d.items() if v}


def _write_open(d: dict[str, list[dict[str, Any]]], now: float) -> None:
    d = {k: sorted((e for e in v if now - e.get("t", 0) < OPEN_WINDOW), key=lambda e: e.get("t", 0)) for k, v in d.items()}
    d = {k: v for k, v in d.items() if v}
    d = _trim(d, OPEN_KEEP, lambda k: k.partition("|")[2])          # per writer: the key is "<item>|<digest of the writer>"
    d = _trim(d, OPEN_TOTAL, lambda k: "")
    p = _open_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def remember(item: str, sender: str, detail: dict[str, dict[str, Any]], now: float | None = None) -> None:
    """Keep the fixes of a call that has a bounce-back check open, for the next write of this sender on this item. Never raises."""
    keep = {k: v for k, v in detail.items() if k in CHECKED}
    if not (item and sender and keep):
        return
    t = time.time() if now is None else now
    try:
        with _LOCK:
            d = _read_open()
            key = f"{item}|{_h(sender)}"
            d[key] = [e for e in d.get(key, []) if e.get("k") not in keep] + [{"k": k, "t": t, "d": v} for k, v in keep.items()]
            _write_open(d, t)
    except Exception:  # noqa: BLE001 — a bounce-back count is not worth a lost reply
        pass


def bounces(item: str, sender: str, args: dict[str, Any], now: float | None = None, since: float | None = None) -> list[str]:
    """The kinds of fix that a call with `args`, by `sender` on `item`, undoes or redoes (each open fix is asked once: a kind that bounced is closed). `since` is when that call began: a fix made after it
    is no reaction (the call could not have read its note), so it is left open. Never raises."""
    if not (item and sender):
        return []
    t = time.time() if now is None else now
    try:
        with _LOCK:
            d = _read_open()
            key = f"{item}|{_h(sender)}"
            open_ = [e for e in d.get(key, []) if t - e.get("t", 0) < OPEN_WINDOW]
            if not open_:
                return []
            hit = [e["k"] for e in open_ if (since is None or e.get("t", 0) <= since) and undone(e["k"], e.get("d") or {}, args)]
            if hit:
                d[key] = [e for e in open_ if e["k"] not in hit]
                _write_open(d, t)
            return hit
    except Exception:  # noqa: BLE001
        return []


_FIELD_OF = {"wake": "the wake", "subject-prefix": "the subject", "item-id": "the item id"}      # what a fix put right, in the words of the line that tells how to keep it as written


def reply_note(fixes: list[tuple[str, str]]) -> str:
    """The text appended to a reply that carries corrections; "" for none (a counted fix and a bounce-back have no line of their own). A fix whose field sent again would change nothing or be refused (NO_RESEND)
    invites no resend; beside a fix that does, the closing line names only the fields of the second kind, so it never asks for the whole write again."""
    told = [(k, n) for k, n in fixes if n]
    if not told:
        return ""
    again = [k for k, _ in told if k not in NO_RESEND]
    if not again:
        tail = "."
    elif len(again) == len(told):
        tail = ". To keep a field as you wrote it, send it again as you want it."
    else:
        tail = f". To keep {' and '.join(dict.fromkeys(_FIELD_OF.get(k, 'a field') for k in again))} as you wrote it, write that field again as you want it; the rest is complete as stored."
    return "\n(fixed for you: " + "; ".join(dict.fromkeys(n for _, n in told)) + tail + ")"


def _file(now: float) -> Path:
    return _cfg.state("calls") / (dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%Y-%m") + ".jsonl")


def size_of(args: Any) -> int:
    """The size in characters of a call's arguments as sent (their JSON text); 0 when there are none or they cannot be measured. Only the size is kept, never the arguments."""
    try:
        return len(json.dumps(args, ensure_ascii=False, default=str, separators=(",", ":"))) if args else 0
    except Exception:  # noqa: BLE001 — a size that cannot be taken is no reason to lose the line
        return 0


def record(tool: str, ok: bool, *, item: str = "", sender: str = "", why: str = "", fixes: list[tuple[str, str]] | None = None, call: str = "", to: str = "", kind: str = "", text: str = "", req: int = -1, rlen: int = -1, now: float | None = None) -> None:
    """Append the line of one call. Never raises: a log line is not worth a lost reply. Every tool's call is logged, a read too (a read that errors is a refusal). `req` is the size in characters of the call's arguments as sent
    (`size_of`) and `rlen` the length of a refusal's whole text before `why` clips it, each only when given: sizes, never content. A line with a `req` also names its item and sender when the call had them (a retry is found by them).
    A call that went through with a fix or a bounce-back also names its item and sender (a later diff of the
    writer's text is then explainable); a refused create has no item, so `call` (a short digest of what it was about) tells one refused create from another. A refused message call names its target (`to`), the refusal's
    kind slug (`kind`) and the message (`text`, newlines kept, clipped to TEXT_MAX), each only when given. A message call the relay handled where it once refused (`handled` among `fixes`) goes through with its sender, target (`to`),
    the kind of the refusal it replaced, `outcome: handled` and `how`."""
    tool = re.sub(r"[^a-z0-9_-]+", "", str(tool or "").lower())[:TOOL_MAX]
    if not tool:
        return
    t = time.time() if now is None else now
    row: dict[str, Any] = {"t": int(t), "tool": tool, "ok": bool(ok)}
    if fixes:
        made = [k for k, _ in fixes if not k.startswith((BOUNCE, HANDLED, NOTE))]
        back = [k[len(BOUNCE):] for k, _ in fixes if k.startswith(BOUNCE)]
        told = [k[len(NOTE):] for k, _ in fixes if k.startswith(NOTE)]
        if made:
            row["fix"] = made
        if back:
            row["bounce"] = back
        if told:
            row["note"] = told
    h_kind, h_how = handled_of(fixes) if ok and tool == "message" else ("", "")
    one_item, one_sender = re.sub(r"\s+", " ", str(item or "")).strip()[:40], re.sub(r"\s+", " ", str(sender or "")).strip()[:80]
    if not ok or fixes:
        row["item"], row["sender"] = one_item, one_sender
    elif req >= 0:
        if one_item:
            row["item"] = one_item
        if one_sender:
            row["sender"] = one_sender
    if req >= 0:
        row["req"] = int(req)
        if ok and tool == "message" and to and not h_kind:          # a message that went through names its target too: the retry of a refused message is matched on it
            row["to"] = re.sub(r"\s+", " ", str(to)).strip()[:TO_MAX]
    if h_kind:          # a message the relay handled where it once refused: the refusal site's kind, the target and what was done, so the weekly count can show it as handled
        row["to"] = re.sub(r"\s+", " ", str(to or "")).strip()[:TO_MAX]
        row["kind"] = re.sub(r"[^a-z0-9-]+", "-", h_kind.lower()).strip("-")[:40]
        row["outcome"] = "handled"
        row["how"] = re.sub(r"[^a-z0-9-]+", "-", h_how.lower()).strip("-")[:HOW_MAX]
    if not ok:
        if call and not row["item"]:
            row["call"] = re.sub(r"\s+", "", str(call))[:16]
        why = re.sub(r"\s+", " ", str(why or "")).strip()
        row["why"] = why if len(why) <= WHY_MAX else why[:WHY_MAX - 1].rstrip() + "…"
        if rlen >= 0:
            row["rlen"] = int(rlen)
        if to:
            row["to"] = re.sub(r"\s+", " ", str(to)).strip()[:TO_MAX]
        if kind:
            row["kind"] = re.sub(r"[^a-z0-9-]+", "-", str(kind).lower()).strip("-")[:40]
        if text and str(text).strip():
            body = str(text).strip()
            row["text"] = body if len(body) <= TEXT_MAX else body[:TEXT_MAX - 1].rstrip() + "…"
    try:
        p = _file(t)
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            first = not p.exists()
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        if first:          # the first line of a month: the files past the retention go
            prune(t)
    except Exception:  # noqa: BLE001 — a log line is never worth a lost reply
        pass


KEEP_MONTHS = 12            # the monthly files kept besides the current one
_MONTH_FILE = re.compile(r"((?!0000)[0-9]{4})-(0[1-9]|1[0-2])\.jsonl")          # ASCII digits and a real month only


def prune(now: float | None = None) -> int:
    """Delete the monthly call-log files older than the current month and the KEEP_MONTHS before it → how many were deleted. Never raises (a log that cannot be pruned is no reason to fail a call).
    A deletion cannot be undone, so the clock is not trusted alone: the KEEP_MONTHS + 1 newest month files by name stay whatever `now` says, and nothing is deleted when `now` is more than a month past the newest file."""
    gone = 0
    try:
        at = dt.datetime.fromtimestamp(time.time() if now is None else now, _cfg.tz())
        here = at.year * 12 + at.month
        found = sorted((m.group(0), int(m.group(1)) * 12 + int(m.group(2))) for p in _cfg.state("calls").iterdir() if (m := _MONTH_FILE.fullmatch(p.name)))
        if not found or here > found[-1][1] + 1:
            return 0
        for name, idx in found[:-(KEEP_MONTHS + 1)]:
            if idx < here - KEEP_MONTHS:
                try:
                    (_cfg.state("calls") / name).unlink()
                    gone += 1
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        pass
    return gone


def read(since: float, until: float) -> Iterator[dict[str, Any]]:
    """The lines with since <= t < until, oldest file first. A line that does not parse is skipped."""
    z = _cfg.tz()
    a, b = dt.datetime.fromtimestamp(since, z), dt.datetime.fromtimestamp(max(until - 1, since), z)
    months, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for name in months:
        p = _cfg.state("calls") / f"{name}.jsonl"
        try:
            lines = newline_lines(p.read_text(encoding="utf-8", errors="replace"))          # a line torn in the middle of a character reads as a line that does not parse, and is skipped
            # a refused message's text may hold a character `splitlines` cuts at (core/lines.py)
        except OSError:
            continue
        for ln in lines:
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("t"), (int, float)) and since <= row["t"] < until:
                yield row


# ---------------------------------------------------------------------------------------------------------------- what a refusal says, as a kind
_KINDS: tuple[tuple[str, str], ...] = (
    (r"next no longer lists", "a step left out of next with no done or dropped"),
    (r"description bullet is \d+ characters", "a description bullet over its limit"),
    (r"outcome_text bullet is \d+ characters", "an outcome_text bullet over its limit"),
    (r"description has \d+ lines", "a description over its line limit"),
    (r"the description must open with its goal", "a description that does not open with its goal"),
    (r"description contains '", "a changelog word in a description"),
    (r"a line of next is \d+ characters", "a line of next over its limit"),
    (r"the subject is \d+ characters", "a subject over its limit"),
    (r"subject must start with", "a subject without a scope prefix"),
    (r"ask must read|this ask has a Decide part|needs an ask line", "an ask in the wrong form"),
    (r"puts two questions in its Decide part", "an ask with a second question in its Decide part"),
    (r"carries no link to it|links a mockup .* but not in its ask", "an ask that approves a design or plan with no link in the ask"),
    (r"Refused: option \d+ ", "an option without its label and line"),
    (r"Refused: said[\[:]", "a said entry in the wrong form"),
    (r"wait on another item's close has no end|wait on news only .* relays has no end", "a wait on another item with no end date"),
    (r"a wait on your own item needs its reason", "a wait set without its reason"),          # this refusal and the four below it name wait_basis as another way to park: they are not a fault of a basis
    (r"waits on a time .*with no reason", "a time wait with no recorded words or basis"),
    (r"clock pushed out", "a date moved later with nothing else changed"),
    (r"a wait runs at most", "a date past the wait cap"),
    (r"next line .* reads as a wait \(", "a line of next that reads as a wait on a live item"),
    (r"waits on .* but its input is missing", "a wait with an input missing"),
    (r"Refused: (?:clear_)?wait_basis\b|wait_basis goes with", "a wait_basis the rule does not take"),
    (r"metadata\.wake must be", "a wake in the wrong form"),
    (r"bad item id", "an item id in the wrong form"),
    (r"needs names more than one mover", "needs naming more than one mover"),
    (r"reword: step", "a reword of another session's step"),
    (r"leaves .* open with no open step|new item has no open step", "an open item left with no open step"),
    (r"this update hands ", "a hand-off with no check or date"),          # before the front agent kind: that refusal names the sessions handed to, none is a front agent
    (r"user-facing agent|not a background agent", "a front agent named as mover"),
    (r"state is a retired input|ranks are retired|(?:is|are) not a parameter any more|is not a parameter of \w+ any more", "a retired input"),
    (r"pass sender=", "no sender"),
    (r"closing \S+ needs ", "a close with a part missing"),
    (r"the reason is \d+ characters", "a close reason over its limit"),
    (r"work: state ", "a status state the work line does not have"),
    (r"clear_wait drops ", "clear_wait sent beside a new wait"),
    (r"a park that waits on a notice from the anchor", "an anchor park with no backstop date"),
    (r"is not on .{0,80}anchors list", "a wait_anchor that is not on the anchors list"),
    (r"wait_kind is one of", "a wait_kind that is none of the kinds"),
    (r"go with a close", "close fields on a write that is no close"),
    (r"status must be open \| completed", "a status that is not open or completed"),
    (r"is not closed and nothing is ticked", "a close with a step still open"),
    (r"work: a status line is a few words", "a status line over its limit"),
    (r"the status of a step on \S+ is written by its mover", "a status line from a session the item does not name"),
    (r"step at most \d+ characters on one line", "a step over its limit"),
    (r"put the text in draft=", "a step to post a text with no draft"),
    (r"has a bare URL", "a bare URL in next or ask"),
    (r"left with .{0,60} as its mover but nothing for", "the owner left as mover with nothing to do"),
    (r"you owe a project-page update", "a page update owed (no longer refused)"),
)
_KIND_RX = tuple((re.compile(p, re.I), name) for p, name in _KINDS)


_COMBINED_RX = re.compile(r"Refused: \d+ problems in this call.*?\s\(1\) (.*?)(?:\s\(2\) |\sNot checked yet|\Z)", re.S)      # faults.combine's shape, with its line breaks or folded to spaces as a logged line is (record)


def kind_of(why: str) -> str:
    """A refusal's text → the kind it is counted under: a named kind of _KINDS, else the text with its ids and numbers folded to 'N' and cut at 70 characters."""
    t = str(why or "")
    if m := _COMBINED_RX.match(t):          # a refusal of several faults (model/faults.py): counted under its first fault, as a refusal of that one alone is
        t = "Refused: " + m.group(1)
    for rx, name in _KIND_RX:
        if rx.search(t):
            return name
    t = re.sub(r"^Refused:\s*", "", t)
    t = re.sub(r"board(?:-tmp-[\w-]+)?#\d+", "ID", t)
    return re.sub(r"\d+", "N", t)[:70].rstrip()
