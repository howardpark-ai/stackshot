"""asks.py: the ask line of a needs=decision item, as the write path keeps it.

The ask is the one line the owner reads on his move (metadata.ask). This module is the I/O half of what the server does with it: the shape gate (`_gate_ask`), the form of the line in `next` for a client whose tool has no
ask parameter (`_ASK_IN_NEXT`, `_next_put`, `_lift_ask`), the nag for an item that needs a decision and has no valid ask (`_ask_owed`), and the leaves of a wrong or moot ask (the pure half is model/ask_leaves.py): the
record of who wrote the ask and when (`_ask_stamp`, a `writes.save` step), the ask that stands now (`_ask_stands`), the lookup of the board item an ask waits on (`_ask_lookup`), the sessions whose word about the ask counts
(`_ask_authors`), the take-off of an ask its author calls wrong (`_ask_leave`) and the tail an update adds for the ask on its item (`_ask_after_write`).

A service module: it reads the store and writes an item only through `writes.save`, under the item lock. The page's parser of an ask line, the board's words for a time and its time zone, and the debounced publish are the
surface's, reached through service/save_hooks.py; the hand-over after his decision is service/answer_handover.py's. A suite that replaces one of these sets it on this module (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import ask_leaves as _askl
from stackshot.model import holders as _holders
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _item_url, _norm_id
from stackshot.model.needs import _canon_needs, _needs_kinds, _needs_of, _needs_store
from stackshot.projects import pages as _pages
from stackshot.service import answer_handover as _handover
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import stall as _stall
from stackshot.waits import watchers as _watch

_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as web/tools/text.py holds it


# ----------------------------------------------------------------------------- the ask line


def _gate_ask(ask: str) -> str:
    """An ask as given → its stored form; the shape refusal whatever the stage."""
    if _hooks().parse_ask(ask) is None:
        raise ToolError(f'Refused: ask must read "{_hooks().ask_form()}" in one line of at most {_hooks().ask_max()} characters')
    return ask.strip()


_ASK_IN_NEXT = "A client whose tool has no ask parameter writes the line as the first line of next instead."


def _next_put(meta: dict[str, Any], text: str, writer: str, keeper: str, **kw: Any) -> list[tuple[str, str]]:
    """nextlines.write for the tools: a next text that cannot sit beside other writers' lines is a refusal. → the lines of the text that another session's open line already reads (left out, not added twice)."""
    try:
        return _nl.write(meta, text, writer, keeper, _handoff.ho_same, **kw)
    except _nl.NextFormError as e:
        raise ToolError(f"Refused: {e}")


def _lift_ask(meta: dict[str, Any], refresh: bool = False, writer: str | None = None, keeper: str = "") -> str:
    """A client whose cached tool schema has no `ask` (a claude.ai chat or Cowork session started before that deploy
    keeps its tool list, and cannot refresh it) writes the ask line as the first line of `next`, the form the daily audit
    already counts (seen on one item). On an item that needs a decision and carries no
    valid ask, that line becomes the ask and leaves `next`, so [ask] refuse_after does not lock such a client out of its own
    items. `refresh` (the call passed `next` itself; after one item's owner could not refresh a
    stale ask): an ask-shaped first line also replaces a valid ask it differs from, and leaves `next` when it repeats it. The
    caller calls it only when its call passed no ask. Next is kept by writer: with `writer` the line looked at is the writer's own first line, never another
    session's, and the indented lines under the ask line leave next with it. → the reply's note, or ""."""
    if "decision" not in _needs_kinds(meta):
        return ""
    had = str(meta.get("ask") or "").strip()
    valid = _hooks().parse_ask(had) is not None or bool(_watch.asked_of(meta))
    if valid and not refresh:
        return ""
    line = _nl.lift_first(meta, lambda ln: _hooks().parse_ask(ln) is not None, writer, keeper, _handoff.ho_same)
    if not line:
        return ""
    meta["ask"] = line
    if valid and line == had:
        return "\n(note: the first line of next repeated the ask line, so it was taken out of next.)"
    if valid:
        return "\n(note: this call passed no ask, so the first line of next, which has the ask's form, replaced the ask line.)"
    return "\n(note: this call passed no ask, so the first line of next, which has the ask's form, was taken as the ask line.)"


def _ask_owed(meta: dict[str, Any]) -> str:
    """A needs=decision item without a valid ask line: before [ask] refuse_after (or with none set) → the nag line for the
    reply; from that date → ToolError. "" when the item has no needs=decision or carries a valid ask."""
    if "decision" not in _needs_kinds(meta) or _hooks().parse_ask(str(meta.get("ask") or "")) is not None or _watch.asked_of(meta):     # a watcher's ask is its own fixed form, while it is up
        return ""
    after = _cfg.ask_refuse_after()
    if after and _pages.zone_now().date() >= dt.date.fromisoformat(after):
        raise ToolError(f'Refused: a needs=decision item needs an ask line: ask="{_hooks().ask_form()}" (≤ {_hooks().ask_max()} chars). {_ASK_IN_NEXT}')
    return (f'\n[ask] a needs=decision item carries an ask line: ask="{_hooks().ask_form()}" (≤ {_hooks().ask_max()} chars'
            + (f"; refused from {_hooks().when_words(dt.date.fromisoformat(after))}" if after else "") + ")\n[ask] " + _ASK_IN_NEXT)

# ----------------------------------------------------------------------------- an ask that is wrong or moot leaves the owner's move (ask_leaves.py)
# The server may take off his move what its author calls wrong, in one plain sentence, and apply what he said. It only removes from his move or applies his word: it never writes an ask,
# closes an item or answers for him, and it acts on the author's own plain sentence, nothing else a session writes. Everything it does is a line in History and in the reply. A board item the
# ask waits on being dropped removes nothing: the author's next write to the item carries a line saying so (_ask_after_write).
def _ask_stamp(item: dict[str, Any], before: dict[str, Any] | None, writer: str) -> None:
    """`writes.save`'s step: keep who wrote the ask and when (metadata.ask_rec). A failure here never fails a write."""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        return
    try:
        was = (before or {}).get("metadata")
        was = was if isinstance(was, dict) else None
        who = (_sr._session_label(writer) or writer) if writer and _askl.changed(meta, was) else ""      # the label may read every machine's sessions.json: only a save that changes the ask needs it
        _askl.stamp(meta, was, who, time.time())
    except Exception as e:  # noqa: BLE001
        print(f"ask: {item.get('id')} record not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _ask_stands(item: dict[str, Any]) -> str:
    """The ask that stands on the owner's move now ("" when none): the open item's ask line with a decision in needs, never a watcher's own ask."""
    if item.get("status") != "open":
        return ""
    meta = item.get("metadata") or {}
    return _askl.standing(meta, _needs_kinds(meta), bool(_watch.asked_of(meta)))


def _ask_lookup(ref: str) -> "tuple[str, str, float, str] | None":
    """(status, outcome, when it was last changed: the close time of a closed item, how it ended in words) of the item a number ("12", from the ask's text) or a store id names; None when it cannot be
    read. An item closed as superseded continues in its replacement: it is followed through the chain to its end and the end's state is returned, so only a chain that ends in a dropped item reads as
    dropped; a replacement that is open or done is where the question went on, and the ask stands."""
    try:
        gid = _norm_id(f"board#{ref}") if ref.isdigit() else _norm_id(ref)
        it = _svcstore._load(gid)
    except Exception:  # noqa: BLE001
        return None
    chain, seen = [], {gid}
    while it.get("status") == "completed" and (it.get("metadata") or {}).get("outcome") == "superseded":
        nxt = str((it.get("metadata") or {}).get("superseded_by") or "")
        if not nxt:
            return None
        try:
            nxt = _norm_id(nxt)
            if nxt in seen:
                return None
            seen.add(nxt)
            chain.append(nxt)
            it = _svcstore._load(nxt)
        except Exception:  # noqa: BLE001
            return None
    try:
        closed = float(it.get("state_updated") or it.get("updated") or 0)
    except (TypeError, ValueError):
        closed = 0.0
    outcome = str((it.get("metadata") or {}).get("outcome") or "")
    how = f"superseded by {_gh.shown(chain[0])}, and the replacement chain ended in {_gh.shown(chain[-1])}, which was {outcome}" if chain else outcome
    return str(it.get("status") or ""), outcome, closed, how


def _ask_when(ts: float) -> str:
    return _hooks().when_words(dt.datetime.fromtimestamp(ts, _hooks().zone()))


def _ask_authors(item: dict[str, Any]) -> "list[str]":
    """The sessions whose own word about the ask counts: the author the record names, else (an ask stored before the record) the session that moves the item and the one that created it."""
    meta = item.get("metadata") or {}
    by = str(_askl.rec_of(meta).get("by") or "")
    if by:
        return [by]
    return [x for x in (_telling.holder(item), str(meta.get("owner") or "")) if x and not _model.is_owner(x)]


def _ask_leave(gid: str, why: str, sender: str = "", expect: str = "") -> str:
    """Take the standing ask off the owner's move: the ask, its options and his stored your-call go, `decision` leaves needs, the item goes back to its author (a live session; else as any answered
    decision's hand-over leaves it), one History line says what and why, and metadata.ask_left keeps the ask and its options so that his late answer is kept as a comment (_answer). Only its
    author's own plain sentence (`why`) calls for it; `expect` = the ask the caller saw, so a write that changed it meanwhile leaves it alone. The server's own save: it
    answers nothing for him, writes no ask and closes nothing. → the reply line ("" when nothing was taken off)."""
    with _writes.ITEM_LOCK:
        try:
            item = _svcstore._load(gid)
        except ToolError:
            return ""
        meta = item.get("metadata")
        ask = _ask_stands(item)
        if not isinstance(meta, dict) or not ask or (expect and ask != expect):
            return ""
        now = time.time()
        rec = _askl.rec_of(meta)
        authors = _ask_authors(item)
        back = next((a for a in ([sender.strip()] if sender.strip() else []) + authors if a and not _model.is_owner(a)), "")
        shown_opts = _hooks().options_of(item)
        meta.pop("ask", None); meta.pop("options", None); meta.pop("idle", None)
        _holders._state_end(meta, "your-call")
        _needs_store(meta, _canon_needs([x for x in _needs_of(meta) if x.lower() != "decision"]))
        if back and _handover._then_live(back, meta):
            meta["then"] = back      # the author takes the item back; read below, so the hand-over sees the `then` set here and not the one stored before
        mover_in, then_in = _model.norm_who(meta.get("mover")), _model.norm_who(meta.get("then"))      # after the line above: _decision_hand_over reads the then that stands now
        meta[_askl.LEFT] = {"at": now, "ask": ask, "how": "word", "why": why[:200], "by": str(rec.get("by") or ""), **({"options": shown_opts} if shown_opts else {})}
        _handover._decision_hand_over(meta, mover_in, then_in, parked=False, waiting=_item_read._model_of({**item, "gid": gid, "metadata": meta}).state == _model.WAITING, now=now)
        _stall.note(meta, now, f"ask taken off {OWNER}'s move by the server (its author said so: {_clip_line(why, 110)}): \"{_clip_line(ask, 90)}\"")
        item["metadata"] = meta
        item["updated"] = item["state_updated"] = item["confirmed"] = now
        _writes.save(gid, item, note="ask taken off his move")
    _hooks().publish()
    item["gid"] = gid
    to = _telling.holder(item)
    line = (f"[stackshot] the ask on {_gh.shown(gid)} was taken off {OWNER}'s move (its author said it is wrong: {_clip_line(why, 140)}). "
            f"The item is back with {_sr._session_label(to) if to else 'its default mover'}. If he answers it late, his answer is kept as a comment → {_item_url(gid) or _telling.notice_link(gid)}")
    if to and not (sender.strip() and _handoff.ho_same(to, sender)):
        try:
            _telling.tell_woken(gid, _hooks().session_id(to), f"{_FOR_OWNER} {line}" if _telling.front_keeper(to, str(meta.get("project") or ""))[0] else line, tag="ask")
        except Exception as e:  # noqa: BLE001  — the ask is off his move; a notice that fails is a stderr line
            print(f"ask: {gid} mover not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    print(f"ask: {gid} taken off the owner's move (its author's word): {why}", file=sys.stderr, flush=True)
    return (f"\n(the server took the ask off {OWNER}'s move: you said it is wrong, \"{_clip_line(why, 110)}\". "
            f"The item is back with {_sr._session_label(to) if to else 'its default mover'}; History says so. His late answer, if one comes, is kept as a comment.)")


def _ask_after_write(pre: "dict[str, Any]", sender: str, ask: str, clear_ask: bool, texts: "list[str]") -> str:
    """An update's tail for the ask on its item (the reply's extra lines). Three things, in this order:
      a write that sets an ask → the ask-time check: his comments and notes since the item's last ask are shown, so one that already answers the ask is seen at the write;
      a write by the ask's author whose ENTIRE new text (every text parameter of the call, _ASK_TEXT_PARAMS in web/tools/update.py; a line the item already held whole is not new) is one plain sentence, "the ask is wrong|moot|stale|...", the closed shape of
        ask_leaves.author_says_wrong → the server takes the ask off his move (_ask_leave);
      a write by the session that wrote the ask, moves the item or created it, while the ask still stands → the one-line reminder to withdraw it if it is wrong or moot, with his notes since the ask; for the
        ask's author it also says which board item the ask waits on was dropped after the ask was written (ask_leaves.dropped_deps), the only thing the server does about a dropped dependency.
    A write that clears the ask, or leaves none, adds nothing. Never fails the write: the update is saved."""
    gid = pre.get("gid") if pre else ""
    if not gid:
        return ""
    try:
        with _writes.ITEM_LOCK:
            item = _svcstore._load(gid)
        now_ask = _ask_stands(item)
        meta = item.get("metadata") or {}
        if not now_ask or clear_ask:
            return ""
        who = sender.strip()      # a write with no sender is nobody's own word: it takes no ask off his move and gets no reminder
        if ask.strip():
            notes = _askl.notes_since(meta, float(pre.get("look") or 0))
            return _askl.check_line(OWNER, _askl.notes_line(notes, _clip_line, _ask_when)) if notes else ""
        authors = _ask_authors(item)
        mine = bool(who) and any(_handoff.ho_same(who, a) for a in authors)
        if _cfg.ask_leaves_on():
            word = _askl.author_says_wrong(_askl.new_lines(texts, str(pre.get("old") or ""))) if mine and pre.get("ask") == now_ask else ""
            if word:
                out = _ask_leave(gid, word, sender=who, expect=now_ask)
                if out:
                    return out
        if mine or (who and _handoff.ho_same(who, _telling.holder(item))) or (who and _handoff.ho_same(who, str(meta.get("owner") or ""))):
            since = float(_askl.rec_of(meta).get("at") or pre.get("look") or 0)
            at = _askl.rec_of(meta).get("at")      # an ask with no record has no time to compare a drop with: nothing is said of its dependencies
            dropped = _askl.dropped_line(_askl.dropped_deps(now_ask, _ask_lookup, float(at)), _ask_when) if mine and at else ""
            return _askl.reminder(_gh.shown(gid), OWNER, _askl.notes_line(_askl.notes_since(meta, since), _clip_line, _ask_when), dropped)
    except Exception as e:  # noqa: BLE001  — the update is saved and published; the ask's lines are a stderr line when they fail
        print(f"ask: {gid} tail not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return ""
