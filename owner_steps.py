"""owner_steps.py — the owner's steps on an item's checklist, made and ticked by the server.

The rules of the Next design this module serves (N2, N4 and N5, for the owner's part only):

  N2  every action is a step, his included: when an item asks him for a decision (needs decision with its ask) or for a step (state your-step), the SERVER adds the open step
      `<owner>: <what to decide>` to the item's checklist: the Decide part of the ask, or the step's one line. Nobody writes it, so it cannot be left out or disagree with the ask.
  N4  a step of his is ticked only by his answer, which the step shows: `<owner>: <what to decide> → <the option he picked>`. A session cannot tick it (an update whose `done` names it is
      refused); it may withdraw its ask or step, which drops the step.
  N5  the checklist and the item's state agree: an open the owner step exists exactly when the item waits on him. The stored fields (needs, ask, options, state, step) stay what decides
      that, and the server keeps the step in line with them on EVERY save (server._owner_steps_on_save, beside the mover settle), so the two cannot drift.

THE STORAGE. A step the server made is an ordinary line of `next` (written by the server, `stackshot`, so no session's update replaces it) and an ordinary step of `metadata.steps`. Beside them
`metadata.owner_step` holds that line's text, the one thing that tells the server's own step from a `<owner>:` line a session wrote: a changed ask rewords the server's step (the old one is dropped,
the new one added: N3), and an answer ticks the server's step and nothing else. A `<owner>:` line a session wrote that says the same as the ask or the step (the cold call's "answer the ask on the item") is
adopted: it is recorded as the server's step and no second one is added beside it. A `<owner>:` line about something else (a session's "review PR 12 when you can") is the session's own:
the server adds its step beside it, and neither his answer, a withdrawn ask nor a `done` touches that line.

Pure functions on an item's metadata dict, no server import (steps and nextlines are the one copy of the checklist and its lines)."""
from __future__ import annotations

from typing import Any

import model as _model
import nextlines as _nl
import steps as _steps

KEY = "owner_step"                 # metadata: the first line of the step the server made (see THE STORAGE)


def recorded(meta: dict[str, Any]) -> str:
    """The step the server recorded on this item."""
    return _steps.clean(meta.get(KEY))
ARROW = " → "
WORDS_MAX = 60                      # a text answer shown after the arrow, cut here


def is_named(text: Any) -> bool:
    """Does the step open with his name (`<owner>:`, or the instance's owner name)? A line naming no one is not counted: whose it is, is not for this module to say (N1 is a later part)."""
    nm = _steps.opener(text)
    return bool(nm) and _model.is_owner(nm)


def line_of(text: Any) -> str:
    """The step the server makes for `text`: `<owner>: <text on one line>`."""
    return f"{_model.owner_display()}: {_steps.clean(text)}"


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
    keys = {_steps.key(t) for t in texts if _steps.clean(t)}
    return [i for i in _open(cl) if _steps.key(cl[i]["text"]) in keys or (alike and ALIKE is not None and ALIKE(cl[i]["text"]))]


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
    want = line_of(text)
    rec = _steps.clean(meta.get(KEY))
    mine = _same(cl, rec, alike=False) if rec else []
    out = "added"
    if mine:
        if _steps.key(rec) == _steps.key(want) or (ALIKE is not None and ALIKE(cl[mine[0]]["text"])):
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


def drop_open(meta: dict[str, Any], keeper: str, by: str, at: float, also: str = "") -> list[str]:
    """The item no longer waits on him (a session withdrew the ask or the step, or moved the item on): the server's step (metadata.owner_step) and any open line that says what the item's old ask did (`also`: the
    text of that ask, for an item that asked before the server made his steps) are dropped by `by`, and leave next. A `<owner>:` line a session wrote about something else stays. → the first lines dropped."""
    cl = _steps.view(meta, keeper=keeper)
    idx = _same(cl, meta.get(KEY), line_of(also) if also else "")
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
    if not any(_steps.key(s["text"]) == _steps.key(rec) for s in _steps.view(meta, keeper=keeper) if s["status"] == _steps.OPEN):
        meta.pop(KEY, None)


def tick(meta: dict[str, Any], keeper: str, by: str, at: float, answer: str, make: str = "", writer: str = "", add: bool = True, apart: bool = False) -> list[str]:
    """His answer ticks his step: the one the server made (metadata.owner_step) while it is open, else an open line that says what `make` does (an item that asked before the server made his steps), and no other
    `<owner>:` line. The step is done by `by` at `at`, shows `→ answer` after its first line, and leaves next. `make`: the step's text, added first (written by `writer`) when none stands, so his answer is on the
    list all the same (`add` false: none is added, a note on his step ticks the step that stands and makes none). `apart`: his answer is to an ask that stands BESIDE a your-step, so the recorded step (the your-step's, which only his Done or a note on it ticks) is left alone: only an open line that
    says what `make` does is ticked, else `make` is added and ticked, and metadata.owner_step stays. → the first lines ticked, [] when there was none (and `make` empty)."""
    keeper = keeper or ""
    cl = _steps.view(meta, keeper=keeper)
    rec = _steps.clean(meta.get(KEY))
    if apart:
        idx = [i for i in (_same(cl, line_of(make), alike=False) if make else []) if _steps.key(cl[i]["text"]) != _steps.key(rec)]
    else:
        idx = (_same(cl, rec) if rec else []) or (_same(cl, line_of(make)) if make else [])
    if not idx and make and add:
        want = line_of(make)
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


def refuse_done(steps_old: list[dict[str, Any]], done_ix: list[int], recorded: Any = "", want: Any = "") -> str:
    """The refusal text (without its `Refused: `) for a `done` that names his step, "" when none does (N4: only his answer ticks it). His step is the one the server made (`recorded`, metadata.owner_step) and an open
    line that says what the ask does (`want`); a `<owner>:` line a session wrote about something else is the session's to tick."""
    keys = {_steps.key(t) for t in (recorded, line_of(want) if want else "") if _steps.clean(t)}
    mine = [i for i in done_ix if steps_old[i]["status"] == _steps.OPEN and is_named(steps_old[i]["text"]) and _steps.key(steps_old[i]["text"]) in keys]
    if not mine:
        return ""
    i = mine[0]
    return (f"done names step {i + 1} ({_steps.first_line(steps_old[i]['text'])[:90]}), which is {_model.owner_display()}'s: only his answer on the board ticks it, and a session cannot tick it for him. "
            "If the step is no longer wanted, withdraw what asks him (clear_ask=true or needs without decision for a decision, or change the state for a your-step) and the server drops his step with it")
