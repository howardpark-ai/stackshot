"""server_fixes.py: the server's facts-only fixes, and the record that keeps them from fighting a mover.

A write or a stored item that is not quite right in a way the server can tell from facts it already holds (a wake that is the whole of a wait, a front agent named mover where the
project has a builder, a wait reason written in the item's own next or description, a past pick quoted in a wait's words) is put right by the server, which then says what was wrong:
the write goes through, the fix is a line in History (`stall.note`, shown as "stackshot: ..."), and the reply (or a message, for a fix made by a pass) names it. The server never closes an
item, never writes an ask, and never changes an item the owner moves (needs decision, the owner as mover).

The fixes (each a key of FIXES):
  wake_park     a wake that is the whole of the mover's wait is parked: hold=true with a wait_basis made from the step's own words (the write: server `_date_only_wait`; the ten-minute filing
                pass: server `_wake_park`, through audit_run.Env.wake_park)
  front_mover   mover, then or post_wake_mover set to a front agent by another session is set to the project's builder instead (server `_fix_front_mover`); with no builder the write is refused as before
  wait_reason   a hold with a wake and no reason, whose own next or description already says what the item waits for on the wake's day, takes that line as its wait_basis (server `_fix_loose_reason`)
  wait_end      a next line that waits in words for another item, a pull request, a machine coming online or a link, with nothing telling the item when that happens, gets the wait the line names
                (after, an event wait, an anchor wait, or a step proof), with a backstop day; the ten-minute filing pass only (server `_wait_end_fix`, wait_end.py, through audit_run.Env.wait_end)
  settled_pick  not a write: the readers that take words for a wait on the owner (board_report's mislabeled-state check, the server's hold note) skip a quoted span and a pick he already made
                (`settled_out`), so a past answer quoted in a wait is no wait on him

A mover who disagrees sends that fix back and the server leaves the field alone: for wait_end `clear_after`, `clear_wait` or `step_proof=none` on what the server set records the line's token in
`metadata.fix_declined` and the pass leaves that line alone; for wake_park `clear_hold=true` on the item the server parked records the wake in `metadata.fix_declined`,
and neither the write nor the pass parks that wake again; for front_mover the same mover value sent again by the session whose write was fixed, less than a day after, goes through as sent
(`metadata.server_fixed` holds the value it substituted, bound to that sender and the time, until it is sent or a day passes; another session sending the value is substituted as a new case);
for wait_reason the mover's own wait_basis in the call is used as given, and for settled_pick nothing is sent back (it is a reading, not a write). A fix is bound to a token (the wake, the
field=value), so a changed value is a new fact. Both keys are the server's bookkeeping and move no clock of the item.
Stdlib plus the repo's stall module."""
from __future__ import annotations

import re
from typing import Any

from stackshot.core import config as _cfg
from stackshot.waits import stall as _stall

MARK = "server_fixed"        # metadata.server_fixed = {fix: [token, ...]}: what the server fixed (the last few tokens)
DECLINED = "fix_declined"    # metadata.fix_declined = {fix: [token, ...]}: tokens the mover sent back
KEEP = 5
BOUND_TTL = 24 * 3600.0     # a fix bound to a sender (front_mover) is the sender's to send back for this long

WAKE_PARK, FRONT_MOVER, WAIT_REASON, SETTLED_PICK, WAIT_END = "wake_park", "front_mover", "wait_reason", "settled_pick", "wait_end"
FIXES = (WAKE_PARK, FRONT_MOVER, WAIT_REASON, SETTLED_PICK, WAIT_END)


def _tokens(meta: dict[str, Any] | None, key: str, fix: str) -> list[str]:
    block = (meta or {}).get(key)
    got = block.get(fix) if isinstance(block, dict) else None
    return [str(x) for x in got] if isinstance(got, list) else []


def marked(meta: dict[str, Any] | None, fix: str, token: str) -> bool:
    """True when the server fixed `fix` for `token` on this item (and the mover has not sent it back or sent the original again)."""
    return str(token) in _tokens(meta, MARK, fix)


def bind(token: str, by: str, now: float) -> str:
    """A token bound to the session whose write was fixed and the time of the fix: "<token>|<by>|<epoch seconds>"."""
    return f"{token}|{by}|{int(now)}"


def marked_by(meta: dict[str, Any] | None, fix: str, token: str, by: str, now: float, ttl: float = BOUND_TTL) -> str:
    """The bound mark (`bind`) of `fix` for `token` that `by` made less than `ttl` seconds ago, else "". Another session's, a stale or a malformed mark does not count."""
    for entry in reversed(_tokens(meta, MARK, fix)):
        t, sep, rest = entry.partition("|")
        who, sep2, at = rest.rpartition("|")
        if t == str(token) and sep and sep2 and who == str(by) and at.isdigit() and 0 <= now - int(at) < ttl:
            return entry
    return ""


def mark_tokens(meta: dict[str, Any] | None, fix: str) -> list[str]:
    return _tokens(meta, MARK, fix)


def mark(meta: dict[str, Any], fix: str, token: str) -> None:
    block = dict(meta[MARK]) if isinstance(meta.get(MARK), dict) else {}
    block[fix] = [*[t for t in _tokens(meta, MARK, fix) if t != str(token)], str(token)][-KEEP:]
    meta[MARK] = block


def unmark(meta: dict[str, Any], fix: str, token: str) -> None:
    left = [t for t in _tokens(meta, MARK, fix) if t != str(token)]
    block = dict(meta[MARK]) if isinstance(meta.get(MARK), dict) else {}
    if left:
        block[fix] = left
    else:
        block.pop(fix, None)
    if block:
        meta[MARK] = block
    else:
        meta.pop(MARK, None)


def declined(meta: dict[str, Any] | None, fix: str, token: str) -> bool:
    """True when the mover sent this fix back for this token: the server leaves it alone until the token changes. Only wake_park is sent back this way."""
    return str(token) in _tokens(meta, DECLINED, fix)


def declined_tokens(meta: dict[str, Any] | None, fix: str) -> list[str]:
    return _tokens(meta, DECLINED, fix)


def decline(meta: dict[str, Any], fix: str, token: str) -> None:
    block = dict(meta[DECLINED]) if isinstance(meta.get(DECLINED), dict) else {}
    block[fix] = [*[t for t in _tokens(meta, DECLINED, fix) if t != str(token)], str(token)][-KEEP:]
    meta[DECLINED] = block


def record(meta: dict[str, Any], fix: str, token: str, history: str, now: float) -> None:
    """The fix on the item: marked for its token, and a History line (the stall log: "stackshot: ...")."""
    mark(meta, fix, token)
    _stall.note(meta, now, history)


# ---- the settled pick: words that quote or record an answer already given are no wait on its giver
_QUOTE_RXS = (re.compile(r"\"[^\"\n]*\""), re.compile("“[^”\n]*”"), re.compile(r"`[^`\n]*`"), re.compile(r"(?<![\w'])'[^'\n]+'(?![\w'])"))
_PAST = r"(?:picked|chose|chosen|decided|approved|answered|confirmed|signed(?:\s+off)?|said|replied|ok'?d|okayed)"


def owner_names() -> list[str]:
    """The names a pick is read against: the owner's name (the generic `the owner` when none is set, as the readers that match the owner do) and his aliases."""
    return list(dict.fromkeys([str(_cfg.owner()), *_cfg.owner_names()]))


_WAITING_BEFORE = re.compile(r"\b(?:until|till|wait(?:s|ing|ed)?|await(?:s|ing)?|pending|blocked|for|on|upon)\s+(?:(?:on|for|upon)\s+)?$", re.I)
_NEGATION = re.compile(r"\b(?:not|never|yet|no)\b|n['’]t\b", re.I)


def settled_out(text: Any, names: list[str] | tuple[str, ...]) -> str:
    """`text` without what cannot be a wait on the owner: every quoted span (double, curly, backtick, single) and each "<owner name> [up to two words] <past verb>" phrase (Oliver picked A,
    Dana has approved): a pick already made. Spans are blanked in place, so nothing around them joins into a new phrase. The rest is as given. Not blanked, because they still wait on him: a quoted
    span that is only his name (blocked on 'Oliver' approval: the quote marks go, the name stays), a phrase whose words between the name and the verb negate it or hold it open (not, n't, never, yet, no:
    "Oliver has not yet decided"), and a phrase right after a waiting word (until, till, wait, awaiting, pending, blocked, for, on, upon: "parked until Oliver confirmed or rejected")."""
    out = str(text or "")
    named = {n.casefold() for n in names if n}

    def quoted(m: "re.Match[str]") -> str:
        body = m.group(0)[1:-1].strip()
        if body.casefold() in named or (body[-2:] in ("'s", "’s") and body[:-2].casefold() in named):
            return " " + m.group(0)[1:-1] + " "         # his name alone in quotes is the name, not a quoted answer
        return " " * len(m.group(0))

    for rx in _QUOTE_RXS:
        out = rx.sub(quoted, out)
    alt = "|".join(re.escape(n) for n in names if n)
    if alt:
        past = re.compile(rf"(?<![A-Za-z0-9_-])(?P<name>{alt})(?![A-Za-z0-9_-])(?P<mid>(?:\s+(?:has|had|already|just|then))?(?:\s+[\w'’-]+){{0,2}}?)\s+{_PAST}\b", re.I)

        def blank(m: "re.Match[str]") -> str:
            if _NEGATION.search(m.group("mid")) or _WAITING_BEFORE.search(out[:m.start()]):
                return m.group(0)
            return " " * len(m.group(0))

        out = past.sub(blank, out)
    return out
