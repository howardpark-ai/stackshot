"""held.py — notices held for a background agent until its next turn (notices that ask nothing of a builder cost a turn each and often end with nothing done).

A notice to a BACKGROUND agent (a `background:` entry of a page's agents map) that asks nothing of it is not delivered as a new turn. It is
held here and handed over with the agent's next turn, whatever caused that turn. Held kinds (KINDS):
  closed      an item the agent moves or observes was closed or completed by another session (telling.tell_owner, tell_observers, tell_owner_change)
  changed     another session changed an item the agent neither moves nor is named on: its next, needs, check or after (tell_owner_change)
  queue       a wake that leaves an item still after an open item: its place in the queue, nothing to do yet (wake_tell in service/wakes.py; for a FRONT agent the same line goes through the front
              gate as an fyi, `_front_queue_row`, and is filed here under this kind)
  page-owed   the keeper's "the page update is owed" notice (pilot_relay, pilot_relay_many; also what the router passes of such a notice, to a front agent too: through the front gate)
  fyi         a message its sender marked fyi (the message tool's `fyi`)
  person      a person's anchor notice the router's read-first gate could not place (router.py, rule `gate-person`): held whole for the project's background agent, never archived, and so never dropped here either:
              a `person` line is exempt from the age limit (KEEP_DAYS), the count limit (KEEP_MAX) and the sweep of an untouched session's file; only an ack of the agent's hook removes it
Everything else wakes the agent as before: a notice that names it in needs, hands it an item (mover, hand-off), ends its wait, carries
the owner's words or asks something; so does the audit's finding for an item's mover (router.py audit-owners): it is a task. When the code is unsure it delivers (decide() answers "" for any kind it does not know).

THE ONE DECISION POINT is decide(): the senders (telling.hold_notice, router_live._hold_kind) pass what they know and take its answer. It
never raises. [router] hold_notices (default true) is the switch; false delivers everything as before.

WHERE THEY LIVE. <state>/held/<key>.jsonl, one file per session, a line per notice {id, ts, kind, text, from, gid, nid}; the key is the
session's permanent id when the registry resolves it, else its transcript id or name (key_of). It is server-side state, so a pane's
conversation cleared or recycled loses nothing, and a restart of the server reloads it from the files.

HOW THEY REACH THE TURN. Every machine's UserPromptSubmit hook (`pages.py nag`, wired by `bin/stackshot client install`) asks the server for
the session's held notices (POST /client/held, the machine's token, the session as the server registered it), prints the answer (the hook's
output is the turn's context), and then acknowledges the ids it printed (a second POST). At least once, never lost: lease() marks the lines it
shows as leased for LEASE seconds and returns their ids; ack() removes them; a line never acknowledged (the hook died before it printed, or
the answer never arrived) is offered again once the lease runs out. A duplicate is possible, a loss is not. Oldest first, one notice each (a message with its line breaks, the lines after the first indented), at
most SHOWN_MAX; the rest stay for the next turn and the last line says "+N more". A notice older than KEEP_DAYS is dropped, and a session
keeps at most KEEP_MAX (the oldest go); each drop is a stderr line. A `person` line (a person's message) is never dropped by any of these: it waits until its agent's hook has handed it over. take() = lease + ack at once (a caller that has no hook to wait for).

ONE LINE OR THE WHOLE TEXT. A status notice the server writes (closed, changed, queue, page-owed, an item's notice to a front agent) is one line, folded to one and cut at LINE_MAX. A message a session wrote
(add(..., whole=True): the message tool's fyi, the router's pass of a message, a queued line filed from a digest) keeps all its words and its line breaks, up to WHOLE_MAX (the message tool's own limit,
MSG_MAX, plus FRAME_ROOM for the sender's label and the framing words): its first line follows the time and the kind, and every line after it is indented two spaces, so the shape stays readable in one turn.
A text above WHOLE_MAX (the tool refuses one above MSG_MAX, so only a text of another source, or a label of unusual length) is cut at a line or word boundary and ends with a note: how many characters were
left out and where the rest is (cut_whole). SHOWN_MAX caps the lines of a turn, whole or not.

ROLLOUT GATE. A notice is held only for a session whose hook has fetched held lines (mark_client, recorded when the endpoint is called;
can_fetch). A machine whose checkout is behind, a cloud session and a session that has not had a turn since the update never fetch, so
they are delivered as today and no line is stranded.

Stdlib only (anchors and config are the repo's own)."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import datetime as dt
import fcntl
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import members as _members
from stackshot.core.lines import MSG_MAX, newline_lines

KINDS = ("closed", "changed", "queue", "page-owed", "fyi", "person")
SHOWN_MAX = 8               # lines handed over at one turn start; the rest wait for the next turn
KEEP_MAX = 100              # held lines kept per session; past it the oldest go (a `person` line is not counted and never goes)
KEEP_DAYS = 7               # a held line older than this is dropped, never handed over (a `person` line is kept)
KEEP_ALWAYS = ("person",)   # the kinds no age limit, count limit or sweep removes: a person's message is never lost to one
LINE_MAX = 260              # characters in one held status line (a text that is not a session's message)
FRAME_ROOM = 400            # characters a held message may carry beyond the message tool's limit: the sender's label and the framing words the notice adds before the text
WHOLE_MAX = MSG_MAX + FRAME_ROOM      # characters in one held message: the message tool's own limit (core/lines.py MSG_MAX) and the room for its frame
WHERE_MAX = 120             # characters of the place a cut message's rest is named in (the note stays short whatever a caller passes)
REST_IN = "the message log (ask the sender for it)"      # where the words of a cut message are, when its caller names no better place
LEASE = 60.0                # s a line handed to a hook stays reserved for it until it acknowledges (then it is offered again)
CLIENT_DAYS = 30            # a session counts as fetching held lines for this long after its hook last asked
_ORD = {1: "st", 2: "nd", 3: "rd"}


def enabled() -> bool:
    """[router] hold_notices: whether notices that ask nothing are held for a background agent (default true; false = every notice is delivered as before)."""
    v = _cfg.get("router", "hold_notices")
    return True if v is None else (v is True or str(v).strip().lower() in ("true", "1", "yes", "on"))


def dir_() -> Path:
    return _cfg.state("held")


def key_of(who: str) -> str:
    """The key a session's held notices are filed under: its permanent id when the registry resolves it, else its transcript id or name as given
    (anchors.canonical turns a name that exactly one live pane carries into that pane's transcript id)."""
    who = str(who or "").strip()
    if not who:
        return ""
    try:
        from stackshot.fleet import sessions_registry as _sr
        pid = _sr.resolve(who)
        if pid:
            return pid
    except Exception:  # noqa: BLE001
        pass
    try:
        from stackshot.anchors import anchors as _anc
        return str(_anc.canonical(who) or who)
    except Exception:  # noqa: BLE001
        return who


def keys_for(*refs: str) -> list[str]:
    """Every key the session may have been filed under, given the references a hook knows (its transcript id, its pane name)."""
    out: list[str] = []
    for r in refs:
        r = str(r or "").strip()
        if not r:
            continue
        for k in (key_of(r), r):
            if k and k not in out:
                out.append(k)
    return out


def _file(key: str) -> Path:
    return dir_() / (re.sub(r"[^A-Za-z0-9._-]", "_", key)[:120] + ".jsonl")


class _locked:
    """An exclusive lock on the store (one lock file for all sessions: the lines are few and the work is short)."""
    def __enter__(self):
        dir_().mkdir(parents=True, exist_ok=True)
        self.f = open(dir_() / "lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def _read(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for ln in newline_lines(path.read_text(encoding="utf-8")):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("text"):
                out.append(d)
    except OSError:
        pass
    return out


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        try:
            path.unlink()
        except OSError:
            pass
        return
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def one_line(text: Any, n: int = LINE_MAX) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def keep_whole(text: Any) -> str:
    """A message's text with its words and line breaks as written: every line ending made "\n" (each character `str.splitlines()` breaks a line at: "\r\n", "\r", a vertical tab, a form feed, the
    separators U+001C to U+001E, U+0085, U+2028 and U+2029, so a reader that cuts the turn with `splitlines()` finds the same lines as the indent), the end of every line and of the text trimmed, blank lines at the start and end dropped."""
    lines = [ln.rstrip() for ln in str(text or "").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def cut_whole(text: str, n: int = WHOLE_MAX, where: str = REST_IN) -> str:
    """`text` whole when it has at most `n` characters. Longer: the note is sized first (with the longest count it can carry) and what is left of `n` is the room for the text. The text is cut at the last
    line break in the second half of that room, else at the last space in the second half, else at the room's end itself (a break or space in the first half is not used: it would drop most of the text),
    and closed with a note on a line of its own, never cut inside it: "… (N characters left out; the rest is in <where>)". `where` is shown at most 120 characters long (folded to one line, cut with an
    ellipsis), so the result is at most `n` characters, the note included, for any `where`."""
    if len(text) <= n:
        return text
    where = one_line(where, WHERE_MAX) or REST_IN
    room = max(0, n - len(f"\n… ({len(text)} characters left out; the rest is in {where})"))      # sized with the longest count the note can carry
    head = text[:room]
    at = head.rfind("\n")
    if at < room // 2:                  # no line break in the second half of what fits: a word boundary there, else the limit itself
        sp = max(head.rfind(" "), at)
        at = sp if sp >= room // 2 else room
    head = head[:at].rstrip()
    return head + f"\n… ({len(text) - len(head)} characters left out; the rest is in {where})"


# ----------------------------------------------------------------------------- the decision
def _owner_mark() -> "re.Pattern[str]":
    """The mark that makes a notice the owner's: "[for <owner>]" with the instance's [instance] owner, or "needs: decision"."""
    owner = _members.first().name
    return re.compile(r"\[for " + re.escape(owner) + r"\]|needs:\s*decision", re.I)


def clients_file() -> Path:
    return dir_() / "clients.json"


def mark_client(*refs: str, now: float | None = None) -> None:
    """A session's hook has asked for its held lines: record it under every key the session may be filed under (can_fetch reads it). Never raises."""
    now = time.time() if now is None else now
    try:
        with _locked():
            d = _clients_read()
            ks = keys_for(*refs)
            if ks and all(now - d.get(k, 0.0) < 3600 for k in ks):
                return          # asked within the hour: every prompt of every session comes here, and the file need not be rewritten each time
            for k in ks:
                d[k] = now
            d = {k: v for k, v in d.items() if now - float(v) <= 3 * CLIENT_DAYS * 86400}
            tmp = clients_file().with_name(".clients.json.tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(tmp, clients_file())
    except Exception:  # noqa: BLE001
        pass


def _clients_read() -> dict[str, float]:
    try:
        d = json.loads(clients_file().read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def can_fetch(target: str, now: float | None = None) -> bool:
    """Does this session's hook fetch held lines (the rollout gate)? False for a session never seen asking, for a cloud session and for one on a
    checkout without the fetch: its notices are delivered as before, never stranded. False on any doubt."""
    now = time.time() if now is None else now
    try:
        d = _clients_read()
        return any(now - d.get(k, 0.0) <= CLIENT_DAYS * 86400 for k in keys_for(target))
    except Exception:  # noqa: BLE001
        return False


def decide(kind: str, *, is_background: bool, text: str = "", owner_words: bool = False, asks: bool = False, sender_is_owner: bool = False, target: str = "") -> str:
    """THE decision: is a notice of this `kind` to this recipient held? → the kind when it is, "" when it is delivered as now.
    Delivered whatever the kind: the switch is off; the kind is none of KINDS; the recipient is not a background agent (a front agent is unchanged);
    the notice carries the owner's words (`owner_words`, or a [for <owner>] mark or "needs: decision" in the text) or its sender is the owner himself
    (`sender_is_owner`); or the caller found that it asks something (`asks`: the agent is named in needs, is the item's mover, a hand-off, a wait that ends);
    or `target` (when given) is not a session whose hook fetches held lines (can_fetch: the rollout gate)."""
    try:
        if kind not in KINDS or not enabled() or not is_background:
            return ""
        if owner_words or sender_is_owner or asks or _owner_mark().search(str(text or "")):
            return ""
        if target and not can_fetch(target):
            return ""
        return kind
    except Exception:  # noqa: BLE001
        return ""


def reason(kind: str) -> str:
    """The routing log's reason for a hold."""
    if kind == "person":
        return "held: a person's message the router could not place, for the agent's next turn (person)"
    return f"held: asks nothing ({kind})"


# ----------------------------------------------------------------------------- the store
def _say(msg: str) -> None:
    print(f"held: {msg}", file=sys.stderr, flush=True)


def _fresh(rows: list[dict[str, Any]], now: float, key: str = "") -> list[dict[str, Any]]:
    """The rows younger than KEEP_DAYS, and every row of a KEEP_ALWAYS kind; a drop is a stderr line (a notice that was never handed over must leave a trace)."""
    keep = [r for r in rows if r.get("kind") in KEEP_ALWAYS or float(r.get("ts", 0)) >= now - KEEP_DAYS * 86400]
    if len(keep) != len(rows):
        _say(f"{len(rows) - len(keep)} notice{'s' if len(rows) - len(keep) != 1 else ''} for {key or 'a session'} dropped unread: older than {KEEP_DAYS} days")
    return keep


def _cap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of a session's file kept to KEEP_MAX: the oldest of the others go, and a KEEP_ALWAYS row is neither counted nor dropped. Order is kept."""
    others = [r for r in rows if r.get("kind") not in KEEP_ALWAYS]
    drop = {id(r) for r in others[:max(0, len(others) - KEEP_MAX)]}
    return [r for r in rows if id(r) not in drop]


def _sweep(now: float) -> None:
    """A session's file nothing has touched for KEEP_DAYS (a retired session, a pane renamed away) holds only expired lines: remove it, or, when it holds a KEEP_ALWAYS line, rewrite it with those alone (a person's message
    stays for whoever reads this file's key next). Caller holds the lock."""
    try:
        for p in dir_().glob("*.jsonl"):
            try:
                if p.stat().st_mtime < now - KEEP_DAYS * 86400:
                    rows = _read(p)
                    kept = [r for r in rows if r.get("kind") in KEEP_ALWAYS]
                    n = len(rows) - len(kept)
                    if kept:
                        _write(p, kept)
                    else:
                        p.unlink()
                    _say(f"{p.stem}: {n} notice{'s' if n != 1 else ''} dropped unread, the session has not had a turn for {KEEP_DAYS} days" + (f" ({len(kept)} kept: a person's message is never dropped)" if kept else ""))
            except OSError:
                pass
    except OSError:
        pass


def add(key: str, kind: str, text: str, sender: str = "", gid: str = "", nid: str = "", now: float | None = None, whole: bool = False, where: str = "") -> bool:
    """Hold one notice for the session `key` (key_of). Idempotent on `nid` (a router notice retried after a write failed is held once).
    `whole`: the text is a session's message, kept with its words and line breaks up to WHOLE_MAX (cut_whole, `where` naming where the rest is when it is cut); otherwise it is folded to one line of at most LINE_MAX.
    → True when stored. Never raises."""
    key = str(key or "").strip()
    line = cut_whole(keep_whole(text), WHOLE_MAX, where or REST_IN) if whole else one_line(text)
    if not key or not line:
        return False
    now = time.time() if now is None else now
    try:
        with _locked():
            _sweep(now)
            p = _file(key)
            rows = _fresh(_read(p), now, key)
            if nid and any(r.get("nid") == nid for r in rows):
                return True
            rows.append({"id": secrets.token_hex(3), "ts": now, "kind": kind, "text": line, "from": one_line(sender, 60), "gid": str(gid or "")[:60], "nid": nid})
            capped = _cap(rows)
            if len(capped) != len(rows):
                _say(f"{len(rows) - len(capped)} notice{'s' if len(rows) - len(capped) != 1 else ''} for {key} dropped unread: more than {KEEP_MAX} waiting")
            _write(p, capped)
        return True
    except Exception:  # noqa: BLE001
        return False


def count(*refs: str) -> int:
    """How many lines wait for the session, leased ones included (no side effect)."""
    n = 0
    try:
        with _locked():
            for k in keys_for(*refs):
                n += len(_read(_file(k)))
    except Exception:  # noqa: BLE001
        pass
    return n


def _when(ts: float, now: float) -> str:
    z = _cfg.tz()
    t, n = dt.datetime.fromtimestamp(ts, z), dt.datetime.fromtimestamp(now, z)
    hm = t.strftime("%H:%M")
    if t.date() == n.date():
        return hm
    d = t.day
    return f"{t.strftime('%a %b')} {d}{'th' if 10 <= d % 100 <= 20 else _ORD.get(d % 10, 'th')} {hm}"


# What the hook's text says above the lines. A person's own message is no notice of another session: it carries its own header, so an agent reads it as a person's words and does not set it aside.
PERSON_HEAD = ("[stackshot] {n} message{s} from a person, held for you while you were busy (chat, mail or thread comment). "
               "READ {what} now, answer or act; if not yours, tell the mover of the item or the person you work for. Handed over once, oldest first:")
OTHER_HEAD = ("[stackshot] {n} notice{s} held for you while you were busy; they asked nothing of you, "
              "come from other sessions or stackshot (not the person, no approval), handed over once, oldest first:")


def _show(r: dict[str, Any], now: float) -> str:
    """One held notice as it reads in the turn: `- <time> · <kind> · <first line>`, and the lines after it (a message with line breaks) indented two spaces. Cut with `splitlines()`, as keep_whole is, so a
    line separator that is no "\n" never leaves a line at column 0 (a stored row is shown the same whoever wrote it)."""
    first, *rest = str(r["text"]).splitlines() or [""]
    return "\n".join([f"- {_when(float(r['ts']), now)} · {r.get('kind', '')} · {first}", *("  " + ln if ln else "" for ln in rest)])


def lease(*refs: str, now: float | None = None, shown_max: int | None = None) -> tuple[str, list[str]]:
    """The text to hand the session at a turn start and the ids of the lines in it → ("", []) when nothing is due. The lines shown are LEASED, not removed:
    ack() removes them, and one never acknowledged is offered again after LEASE seconds (at least once; a duplicate is possible, a loss is not). Lines
    under another offer's lease are not offered. A person's lines come first under their own header (PERSON_HEAD: a person wrote them, read and answer them), then the other notices under theirs (OTHER_HEAD: they ask nothing of you). Oldest first, each notice one line (a message keeps its line breaks: the lines after the first are indented), SHOWN_MAX notices at most, and a last line "+N more" for those that wait for the
    next turn. Never raises."""
    now = time.time() if now is None else now
    cap = SHOWN_MAX if shown_max is None else max(1, shown_max)
    try:
        with _locked():
            keys = keys_for(*refs)
            paths = list(dict.fromkeys(_file(k) for k in keys))
            allrows: dict[Path, list[dict[str, Any]]] = {p: _fresh(_read(p), now, keys[0] if keys else "") for p in paths}
            due: list[tuple[Path, dict[str, Any]]] = [(p, r) for p, rs in allrows.items() for r in rs if float(r.get("lease", 0)) <= now]
            due.sort(key=lambda x: (x[1].get("kind") != "person", float(x[1].get("ts", 0))))      # a person's lines first, so a crowd of other notices never pushes one past the limit
            shown, rest = due[:cap], due[cap:]
            for _p, r in shown:
                r["lease"] = now + LEASE
            for p, rs in allrows.items():
                if p.exists() or rs:
                    _write(p, rs)
            if not shown:
                return "", []
        ppl = [r for _p, r in shown if r.get("kind") == "person"]
        oth = [r for _p, r in shown if r.get("kind") != "person"]
        more = [f"- +{len(rest)} more, handed over at your next turn"] if rest else []
        parts: list[str] = []
        if ppl:
            parts.append(PERSON_HEAD.format(n=len(ppl), s="s" if len(ppl) != 1 else "", what="them" if len(ppl) != 1 else "it") + "\n" + "\n".join([_show(r, now) for r in ppl] + ([] if oth else more)))
        if oth:
            k = len(oth) + (0 if ppl else len(rest))      # without a person's line the count is what it always was: every notice, the ones still waiting included
            parts.append(OTHER_HEAD.format(n=k, s="s" if k != 1 else "") + "\n" + "\n".join([_show(r, now) for r in oth] + more))
        return "\n\n".join(parts), [str(r["id"]) for _p, r in shown]
    except Exception:  # noqa: BLE001
        return "", []


def ack(*refs: str, ids: list[str] | None = None) -> int:
    """The hook printed these lines: remove them. → how many were removed. An id the session does not hold is ignored. Never raises."""
    want = {str(i) for i in (ids or []) if i}
    if not want:
        return 0
    n = 0
    try:
        with _locked():
            for p in dict.fromkeys(_file(k) for k in keys_for(*refs)):
                rows = _read(p)
                keep = [r for r in rows if str(r.get("id")) not in want]
                if len(keep) != len(rows):
                    n += len(rows) - len(keep)
                    _write(p, keep)
    except Exception:  # noqa: BLE001
        pass
    return n


def take(*refs: str, now: float | None = None, shown_max: int | None = None) -> str:
    """lease() and ack() in one step: the text, with the lines it shows removed at once (each handed over once). For a caller with no hook to wait for. Never raises."""
    text, ids = lease(*refs, now=now, shown_max=shown_max)
    ack(*refs, ids=ids)
    return text


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "count":
        print(count(*sys.argv[2:]))
    else:
        print(__doc__)
