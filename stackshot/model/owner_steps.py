"""owner_steps.py — the owner's steps on an item's checklist, made and ticked by the server.

The rules of the Next design this module serves (N2, N4 and N5, for the owner's part only):

  N2  every action is a step, his included: when an item asks him for a decision (needs decision with its ask) or for a step (state your-step), the SERVER adds the open step
      `<owner>: <what to decide>` to the item's checklist: the Decide part of the ask, or the step's one line. Nobody writes it, so it cannot be left out or disagree with the ask.
  N4  a step of his is ticked only by his answer, which the step shows: `<owner>: <what to decide> → <the option he picked>`. A session cannot tick it (an update whose `done` names it is
      refused); it may withdraw its ask or step, which drops the step.
  N5  the checklist and the item's state agree: an open the owner step exists exactly when the item waits on him. The stored fields (needs, ask, options, state, step) stay what decides
      that, and the server keeps the step in line with them on EVERY save (mover_steps._owner_steps_on_save, beside the mover settle), so the two cannot drift.

THE STORAGE. A step the server made is an ordinary line of `next` (written by the server, `stackshot`, so no session's update replaces it) and an ordinary step of `metadata.steps`. Beside them
`metadata.owner_step` holds that line's text, the one thing that tells the server's own step from a `<owner>:` line a session wrote: a changed ask rewords the server's step (the old one is dropped,
the new one added: N3), and an answer ticks the server's step and nothing else. A `<owner>:` line a session wrote that says the same as the ask or the step (the cold call's "answer the ask on the item") is
adopted: it is recorded as the server's step and no second one is added beside it. A `<owner>:` line about something else (a session's "review PR 12 when you can") is the session's own:
the server adds its step beside it, and neither his answer, a withdrawn ask nor a `done` touches that line.

His name stands once: a text that already opens with it (any spelling is_named accepts) is not named again by line_of, and every comparison of a step with the server's line goes by steps.owner_key, so a step
stored with the name twice (made before this) is still the same step and no stored data changes.

Pure functions on an item's metadata dict, no server import (steps and nextlines are the one copy of the checklist and its lines)."""
from __future__ import annotations

from typing import Any

from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import steps as _steps

KEY = "owner_step"                 # metadata: the first line of the step the server made (see THE STORAGE)
ROUTE_KEY = "item_sync_step"       # metadata: the open step a script's route added itself (service/item_sync.py), as the route sent it; it says which open line is the route's own, and goes when that line is no longer open or the item closes (states.CLOSE_EXTRA)
SENT_KEY = "item_sync_sent"        # metadata: the step that route last sent and had on the item, which it never asks again; it stays when the line goes, but is stored empty when a wait took it unanswered
ANSWERED_KEY = "item_sync_answered"      # metadata: true once he answered the step of an item such a route filed; the route then asks him nothing more on that item


def recorded(meta: dict[str, Any]) -> str:
    """The step the server recorded on this item."""
    return _steps.clean(meta.get(KEY))
ARROW = " → "
WORDS_MAX = 60                      # a text answer shown after the arrow, cut here


def is_named(text: Any) -> bool:
    """Does the step open with his name (`<owner>:`, or the instance's owner name)? A line naming no one is not counted: whose it is, is not for this module to say (N1 is a later part)."""
    nm = _steps.opener(text)
    return bool(nm) and _model.is_owner(nm)


def line_of(text: Any, meta: dict[str, Any] | None = None) -> str:
    """The step the server makes for `text`: `<owner>: <text on one line>`, the owner being the item's member (`meta`: the item's metadata; the first member when none is given). A text that already
    opens with a member's name (is_named: any case, a role in parentheses, a list marker or bold marks around it, however many times) gets none put in front: it reads the same written with the
    name or without, and the line keeps the member it opens with."""
    nm = _steps.opener(text)
    who = _model.norm_who(nm) if nm and _model.is_owner(nm) else _model.owner_display(meta)
    return f"{who}: {_steps.without_owner(text)}"


def same_line(a: Any, b: Any) -> bool:
    """Do two lines read as one step of his: the same words, his name once or twice or in another spelling aside (steps.owner_key). A line stored with the name twice is one with it written once."""
    return _steps.owner_key(a) == _steps.owner_key(b)


def decide_of(ask: Any) -> str:
    """The Decide part of an ask line (`Decide: … · Recommend: … · Stakes: … · By: …`), else the ask itself without a leading `Decide:` and cut at its first ` · ` (a watcher's ask has another shape)."""
    t = _steps.clean(ask)
    if t.lower().startswith("decide:"):
        t = t[len("decide:"):].strip()
    return t.split(" · ", 1)[0].strip()


def answer_words(choice: Any, text: Any) -> str:
    """What the step shows after the arrow for his answer: the option's label, else his words, cut (quoted)."""
    c, t = _steps.clean(choice), _steps.clean(text)
    if c:
        return c
    return f'"{t if len(t) <= WORDS_MAX else t[:WORDS_MAX].rstrip() + "…"}"' if t else ""


def with_answer(text: str, answer: str) -> str:
    """The step's text with `→ answer` after its first line (a step with lines under it keeps them)."""
    if not answer:
        return text
    lines = str(text).split("\n")
    lines[0] = lines[0].rstrip() + ARROW + answer
    return "\n".join(lines)


def _open(cl: list[dict[str, Any]]) -> list[int]:
    return [i for i, s in enumerate(cl) if s["status"] == _steps.OPEN and is_named(s["text"])]


ALIKE: Any = None     # set by the server: a predicate for a line a script of the server's own writes as the step itself (the terminal prompt's `<owner>: open <pane> and answer: …`); such a line is his step, adopted like an equal one


def _same(cl: list[dict[str, Any]], *texts: Any, alike: bool = True) -> list[int]:
    """The open lines of his that read as one of `texts` (steps.key: the first line, case and spacing aside), or are the server's own script's line for the step (ALIKE; `alike=False` leaves those out).
    A `<owner>:` line a session wrote about something else is never one of them."""
    keys = {_steps.owner_key(t) for t in texts if _steps.clean(t)}
    return [i for i in _open(cl) if _steps.owner_key(cl[i]["text"]) in keys or (alike and ALIKE is not None and ALIKE(cl[i]["text"]))]


def _put_steps(meta: dict[str, Any], cl: list[dict[str, Any]]) -> None:
    meta["steps"] = _steps.stored(cl)


def _mark(cl: list[dict[str, Any]], idx: list[int], status: str, by: str, at: float, answer: str = "") -> list[str]:
    """Mark the steps `idx` of the checklist `cl` in place → the first lines marked."""
    out = []
    for i in idx:
        out.append(_steps.first_line(cl[i]["text"]))
        cl[i] = {"text": with_answer(cl[i]["text"], answer) if status == _steps.DONE else cl[i]["text"], "status": status, "by": by, "at": at}
    return out


def ensure(meta: dict[str, Any], text: Any, keeper: str, by: str, at: float, writer: str) -> str:
    """The item waits on him for `text`: make sure its checklist holds the open step for it. → "" when nothing changed (a step of the server's already says it, or a `<owner>:` line a session
    wrote is adopted), "added" when the step was added at the end (where it was asked), "reworded" when the server's step said something else (the ask changed): the old one is dropped by `by` and the
    new one added, N3. `writer` is the name the line is written under (the server's, not a session's)."""
    cl = _steps.view(meta, keeper=keeper)
    want = line_of(text, meta)
    rec = _steps.clean(meta.get(KEY))
    mine = _same(cl, rec, alike=False) if rec else []
    out = "added"
    if mine:
        if same_line(rec, want) or (ALIKE is not None and ALIKE(cl[mine[0]]["text"])):
            return ""
        gone = [cl[mine[0]]["text"]]
        _mark(cl, [mine[0]], _steps.DROPPED, by, at)
        _nl.prune(meta, gone, keeper)
        out = "reworded"
    elif _same(cl, want):
        meta[KEY] = _steps.first_line(cl[_same(cl, want)[0]]["text"])                       # a line a session wrote that says the same stands: adopted as the server's step, none is added beside it
        return ""
    _nl.append(meta, want, writer, keeper)
    cl.append({"text": want, "status": _steps.OPEN, "by": "", "at": 0})
    meta[KEY] = want
    _put_steps(meta, cl)
    return out


def reword(meta: dict[str, Any], text: Any, keeper: str) -> bool:
    """The server words its own question again, which asks nothing new: the open step it recorded says `text` now, where it stands (the same step, its place, writer and the member it opens with kept). `ensure`
    would drop it and add one, as it does for a changed ask. → whether there was such a step."""
    cl = _steps.view(meta, keeper=keeper)
    rec = _steps.clean(meta.get(KEY))
    mine = _same(cl, rec, alike=False) if rec else []
    if not mine:
        return False
    old = cl[mine[0]]["text"]
    nm = _steps.opener(old)
    want = line_of(f"{nm}: {text}" if nm else text, meta)
    if not _nl.reword(meta, old, want, keeper):
        return False
    cl[mine[0]] = {**cl[mine[0]], "text": want}
    meta[KEY] = want
    _put_steps(meta, cl)
    return True


def drop_open(meta: dict[str, Any], keeper: str, by: str, at: float, also: str = "") -> list[str]:
    """The item no longer waits on him (a session withdrew the ask or the step, or moved the item on): the server's step (metadata.owner_step) and any open line that says what the item's old ask did (`also`: the
    text of that ask, for an item that asked before the server made his steps) are dropped by `by`, and leave next. A `<owner>:` line a session wrote about something else stays. → the first lines dropped."""
    cl = _steps.view(meta, keeper=keeper)
    idx = _same(cl, meta.get(KEY), line_of(also, meta) if also else "")
    if not idx:
        if meta.pop(KEY, None) is not None and "steps" in meta:
            _put_steps(meta, cl)
        return []
    texts = [cl[i]["text"] for i in idx]
    out = _mark(cl, idx, _steps.DROPPED, by, at)
    _nl.prune(meta, texts, keeper)
    meta.pop(KEY, None)
    _put_steps(meta, cl)
    return out


def forget_closed(meta: dict[str, Any], keeper: str) -> None:
    """Forget the recorded step (metadata.owner_step) once its line is no longer open (ticked, dropped, or left next by a write that knew nothing of steps)."""
    rec = _steps.clean(meta.get(KEY))
    if not rec:
        meta.pop(KEY, None)
        return
    if not any(same_line(s["text"], rec) for s in _steps.view(meta, keeper=keeper) if s["status"] == _steps.OPEN):
        meta.pop(KEY, None)


def route_answered(meta: dict[str, Any]) -> None:
    """He answered the step of an item a script's route filed (a Done, or a note that names no later time): kept on the item (ANSWERED_KEY), also when a wait had taken the line and nothing was left to tick."""
    if "item_sync" in meta:
        meta[ANSWERED_KEY] = True


def route_writes(meta: dict[str, Any], own: str, sent: str, sets_step: bool) -> None:
    """The record a script's route stores with its write (service/item_sync.py): `own`, the step of the open line that is the route's own ("" when none is), and `sent`, the step it sent. A write that
    sets the step (`sets_step`) also lets the server's line for the step before it go, not reworded, so a line that is not the route's stays open (the route drops its own line itself, with a dropped mark)."""
    if sets_step:
        meta.pop(KEY, None)
    meta.pop(ROUTE_KEY, None)
    if own:
        meta[ROUTE_KEY] = own
    meta[SENT_KEY] = sent


def forget_route_closed(meta: dict[str, Any], keeper: str) -> None:
    """Forget a route's record of its own step (ROUTE_KEY) once no open line reads as it (his answer, a drop, a rewording), so a line written later with the same words is not taken for the route's."""
    own = _steps.clean(meta.get(ROUTE_KEY))
    if own and not any(same_line(s["text"], line_of(own, meta)) for s in _steps.view(meta, keeper=keeper) if s["status"] == _steps.OPEN):
        meta.pop(ROUTE_KEY, None)


def route_line(meta: dict[str, Any], keeper: str) -> str:
    """The checklist line that is a script route's own: its step in ROUTE_KEY; on an item the route filed before it kept records (neither key is stored), the first line, when that was written under the item's creator. "" for none."""
    if ROUTE_KEY in meta or SENT_KEY in meta:
        own = _steps.clean(meta.get(ROUTE_KEY))
        return line_of(own, meta) if own else ""
    first = next(iter(_steps.view(meta, keeper=keeper)), None) if "item_sync" in meta else None
    return first["text"] if first and first.get("writer") == keeper else ""


def route_settled(meta: dict[str, Any], step: str) -> None:
    """`step`, which the item stores, was replaced or withdrawn by a session. When a wait had taken its line unanswered (SENT_KEY stored empty), it counts as sent again."""
    if meta.get(SENT_KEY) == "" and _steps.clean(step):
        meta[SENT_KEY] = _steps.clean(step)


def route_replaced(meta: dict[str, Any], keeper: str, step: str, stored: str) -> None:
    """A session's write withdrew the step (`step` "") or set `step`; `stored` is the step the item stored before it. When that takes the server's line (KEY) and it is the route's own, in other words than `step`, the line is
    the route's no more: the text the route sent stays sent, whatever then drops the line, a wait too (route_wait_dropped). The same holds for a `stored` step whose line a wait took earlier (route_settled)."""
    if stored and not (step and same_line(line_of(stored, meta), line_of(step, meta))):
        route_settled(meta, stored)
    line = route_line(meta, keeper)
    if not line or not same_line(line, meta.get(KEY)) or (step and same_line(line, line_of(step, meta))):
        return
    meta.pop(ROUTE_KEY, None)
    meta.setdefault(SENT_KEY, _steps.without_owner(_steps.first_line(line)))


def route_wait_dropped(meta: dict[str, Any], line: str, dropped: list[str]) -> None:
    """A wait took the lines `dropped` off his list. When one is `line`, the route's own (route_line, read before the drop), he never answered it: no step counts as sent (SENT_KEY stored empty), so a repeat open after the wait
    asks it again."""
    if line and any(same_line(t, line) for t in dropped):
        meta[SENT_KEY] = ""


def tick(meta: dict[str, Any], keeper: str, by: str, at: float, answer: str, make: str = "", writer: str = "", add: bool = True, apart: bool = False) -> list[str]:
    """His answer ticks his step: the one the server made (metadata.owner_step) while it is open, else an open line that says what `make` does (an item that asked before the server made his steps), and no other
    `<owner>:` line. The step is done by `by` at `at`, shows `→ answer` after its first line, and leaves next. `make`: the step's text, added first (written by `writer`) when none stands, so his answer is on the
    list all the same (`add` false: none is added, a note on his step ticks the step that stands and makes none). `apart`: his answer is to an ask that stands BESIDE a your-step, so the recorded step (the your-step's, which only his Done or a note on it ticks) is left alone: only an open line that
    says what `make` does is ticked, else `make` is added and ticked, and metadata.owner_step stays. → the first lines ticked, [] when there was none (and `make` empty)."""
    keeper = keeper or ""
    cl = _steps.view(meta, keeper=keeper)
    rec = _steps.clean(meta.get(KEY))
    if apart:
        idx = [i for i in (_same(cl, line_of(make, meta), alike=False) if make else []) if _steps.key(cl[i]["text"]) != _steps.key(rec)]
    else:
        idx = (_same(cl, rec) if rec else []) or (_same(cl, line_of(make, meta)) if make else [])
    if not idx and make and add:
        want = line_of(make, meta)
        _nl.append(meta, want, writer, keeper)
        cl.append({"text": want, "status": _steps.OPEN, "by": "", "at": 0})
        idx = [len(cl) - 1]
    if not idx:
        return []
    texts = [cl[i]["text"] for i in idx]
    out = _mark(cl, idx, _steps.DONE, by, at, answer)
    _nl.prune(meta, texts, keeper)
    if not apart:
        meta.pop(KEY, None)
    _put_steps(meta, cl)
    return out


def refuse_done(steps_old: list[dict[str, Any]], done_ix: list[int], recorded: Any = "", want: Any = "", meta: dict[str, Any] | None = None) -> str:
    """The refusal text (without its `Refused: `) for a `done` that names his step, "" when none does (N4: only his answer ticks it). His step is the one the server made (`recorded`, metadata.owner_step) and an open
    line that says what the ask does (`want`); a `<owner>:` line a session wrote about something else is the session's to tick."""
    keys = {_steps.owner_key(t) for t in (recorded, line_of(want, meta) if want else "") if _steps.clean(t)}
    mine = [i for i in done_ix if steps_old[i]["status"] == _steps.OPEN and is_named(steps_old[i]["text"]) and _steps.owner_key(steps_old[i]["text"]) in keys]
    if not mine:
        return ""
    i = mine[0]
    return (f"done names step {i + 1} ({_steps.first_line(steps_old[i]['text'])[:90]}), which is {_model.norm_who(_steps.opener(steps_old[i]['text']))}'s: only his answer on the board ticks it, and a session cannot tick it for him. "
            "If the step is no longer wanted, withdraw what asks him (clear_ask=true or needs without decision for a decision, or change the state for a your-step) and the server drops his step with it")
