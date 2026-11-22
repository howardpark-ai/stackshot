"""call_log.py — the count of board writes the server refused, and the small corrections it made instead of refusing.

The server writes one line per call of a counted write tool (create, update, complete, confirm, message) to `<paths.state>/calls/<YYYY-MM>.jsonl`:

    {"t": epoch seconds, "tool": "update", "ok": true}                                          the call went through
    {"t": …, "tool": "update", "ok": true, "fix": ["wake", "item-id"]}                           it went through after the server corrected a field itself (see `fixed`)
    {"t": …, "tool": "update", "ok": false, "item": "board#N", "sender": "my-x", "why": "…"}    the server refused it (the ToolError's text, whitespace folded, clipped)

`tools/refusal_report.py` reads these lines for its weekly report. The call's other arguments are never logged: a description, a draft or a said line stays out.

    {"t": …, "tool": "update", "ok": true, "bounce": ["wake_park"]}                             it went through and the writer sent a fix of the server's back (see `bounces`)

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

COUNTED = ("create", "update", "complete", "confirm", "message")      # the write tools whose calls are counted
WHY_MAX = 300                                                         # characters of a refusal's text kept

BOUNCE = "bounce:"            # a fix kind written as BOUNCE + kind is a bounce-back, not a fix (`bounced`)
NO_RESEND = frozenset({"description-bullet", "step-none", "his-step-settled", "step-none-applied", "said-text", "step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url", "wait-basis-dropped", "description-goal"})   # fixes whose reply line does not invite a resend: the field sent again as written would be refused, fixed the same, change nothing, or be settled the same way (each line says how to change it)

_FIXES: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar("call_log_fixes", default=None)
_DETAIL: contextvars.ContextVar[dict[str, dict[str, Any]] | None] = contextvars.ContextVar("call_log_detail", default=None)
_LOCK = threading.Lock()
OPEN_WINDOW = 3600.0            # a fix is open to a bounce-back for this long: the writer's next move on the item (a later write after it is no reaction to the fix)
OPEN_KEEP = 100                 # fixes kept open for one writer at once (that writer's oldest go first: another writer's fixes never push one out)
OPEN_TOTAL = 2000               # fixes kept open in all (the oldest go first): the bound of the file, however many writers there are


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


def counted(kind: str, **detail: Any) -> None:
    """A fix of the server's own kind (server_fixes.record) whose reply already tells it in its own words: counted in the log, no line added to the reply."""
    fixed(kind, "", **detail)


# ---------------------------------------------------------------------------------------------------------------- bounce-backs: the writer undoes or redoes what the server did
# A bounce-back is the writer reacting to a fix it was told about: a later write by the same writer, on the same item, within OPEN_WINDOW, that undoes the fix or writes the fixed field again as it wants it.
# A plain retry after a refusal is none (nothing was fixed). The middleware keeps each fix that has a check open (`remember`) and asks of each later write by that writer on that item whether it undid one (`bounces`).
# The check per kind is cheap and reads only the later call's arguments against what the fix left:
#   wake, subject-prefix, description-bullet, subject-cut, description-url   the later call writes the same field with a value other than the one the server stored and the one the writer sent first (the same text again is no send-back)
#   wake_park                                  the later call sends clear_hold or clear_wake, or a wake other than the parked one
#   wait_reason                                the later call sends a wait_basis, clear_wait_basis, clear_hold or clear_wake
#   front_mover                                the later call names the front agent again in the field the server substituted
# Not checked, because nothing the writer sends later can tell: item-id (the item meant is the item written), step-none (the server changed nothing), his-step-settled, step-none-applied and said-text (the writer's retry is no undoing: it is the same write settled again, or the same said), step-kept (the writer's later mark or reword is no send-back: it is what the line asks for), work-cut and ask-by-day (a shorter line or another day is the intended next write), wait-basis-dropped (the basis sent again is dropped again: nothing a later write sends tells a send-back), description-goal (the label sent as it was is relabelled again; a later description is an edit, not an undoing), settled_pick (a reading, not a write), and the fixes the
# audit's passes make (no writer, so no fix is counted either; their send-back stays in metadata.fix_declined). A write that began before the fix was made could not have read its note: it is no bounce-back.
# What open-fixes.json holds: per writer and item, the kind, the time, and digests (never text) of the value stored and sent; a writer's name is a digest in the key. It errs low by design: a record
# goes after an hour, past OPEN_KEEP for one writer or past OPEN_TOTAL in all.
CHECKED = ("wake", "subject-prefix", "description-bullet", "subject-cut", "description-url", "wake_park", "wait_reason", "front_mover")


def _arg(a: dict[str, Any], k: str) -> str:
    v = a.get(k)
    return v.strip() if isinstance(v, str) else ""


def undone(kind: str, d: dict[str, Any], a: dict[str, Any]) -> bool:
    """Does a later call with arguments `a` undo or redo the fix `kind` that left `d` (the detail `fixed` was given: its stored, sent and token are digests)?"""
    if kind in ("wake", "subject-prefix", "description-bullet", "subject-cut", "description-url"):
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
    return "\n(fixed for you: " + "; ".join(n for _, n in told) + tail + ")"


def _file(now: float) -> Path:
    return _cfg.state("calls") / (dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%Y-%m") + ".jsonl")


def record(tool: str, ok: bool, *, item: str = "", sender: str = "", why: str = "", fixes: list[tuple[str, str]] | None = None, call: str = "", now: float | None = None) -> None:
    """Append the line of one call. Never raises: a log line is not worth a lost reply. A call that went through with a fix or a bounce-back also names its item and sender (a later diff of the
    writer's text is then explainable); a refused create has no item, so `call` (a short digest of what it was about) tells one refused create from another."""
    if tool not in COUNTED:
        return
    t = time.time() if now is None else now
    row: dict[str, Any] = {"t": int(t), "tool": tool, "ok": bool(ok)}
    if fixes:
        made = [k for k, _ in fixes if not k.startswith(BOUNCE)]
        back = [k[len(BOUNCE):] for k, _ in fixes if k.startswith(BOUNCE)]
        if made:
            row["fix"] = made
        if back:
            row["bounce"] = back
    if not ok or fixes:
        row["item"] = re.sub(r"\s+", " ", str(item or "")).strip()[:40]
        row["sender"] = re.sub(r"\s+", " ", str(sender or "")).strip()[:80]
    if not ok:
        if call and not row["item"]:
            row["call"] = re.sub(r"\s+", "", str(call))[:16]
        why = re.sub(r"\s+", " ", str(why or "")).strip()
        row["why"] = why if len(why) <= WHY_MAX else why[:WHY_MAX - 1].rstrip() + "…"
    try:
        p = _file(t)
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 — a log line is never worth a lost reply
        pass


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
            lines = p.read_text(encoding="utf-8").splitlines()
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
    (r"description has \d+ lines", "a description over its line limit"),
    (r"the description must open with its goal", "a description that does not open with its goal"),
    (r"description contains '", "a changelog word in a description"),
    (r"a line of next is \d+ characters", "a line of next over its limit"),
    (r"the subject is \d+ characters", "a subject over its limit"),
    (r"subject must start with", "a subject without a scope prefix"),
    (r"ask must read|this ask has a Decide part|needs an ask line", "an ask in the wrong form"),
    (r"Refused: option \d+ ", "an option without its label and line"),
    (r"Refused: said[\[:]", "a said entry in the wrong form"),
    (r"wait on another item's close has no end|wait on news only .* relays has no end", "a wait on another item with no end date"),
    (r"wait_basis", "a wait_basis the rule does not take"),
    (r"metadata\.wake must be", "a wake in the wrong form"),
    (r"bad item id", "an item id in the wrong form"),
    (r"waits on a time .* with no reason|a wait on your own item needs its reason|clock pushed out", "a wait set without its reason"),
    (r"needs names more than one mover", "needs naming more than one mover"),
    (r"reword: step", "a reword of another session's step"),
    (r"leaves .* open with no open step|new item has no open step", "an open item left with no open step"),
    (r"this update hands ", "a hand-off with no check or date"),          # before the front agent kind: that refusal names the sessions handed to, none is a front agent
    (r"user-facing agent|not a background agent", "a front agent named as mover"),
    (r"state is a retired input|ranks are retired", "a retired input"),
    (r"pass sender=", "no sender"),
)
_KIND_RX = tuple((re.compile(p, re.I), name) for p, name in _KINDS)


def kind_of(why: str) -> str:
    """A refusal's text → the kind it is counted under: a named kind of _KINDS, else the text with its ids and numbers folded to 'N' and cut at 70 characters."""
    t = str(why or "")
    for rx, name in _KIND_RX:
        if rx.search(t):
            return name
    t = re.sub(r"^Refused:\s*", "", t)
    t = re.sub(r"board(?:-tmp-[\w-]+)?#\d+", "ID", t)
    return re.sub(r"\d+", "N", t)[:70].rstrip()
