"""step_settle.py — the server settles the step of his that a write left first in `next` under an agent's state, instead of refusing the write and naming the way out.

The step guard (gates.gate_owner_step) refuses a write whose result has his step as the first line of `next` while the item stands in an agent's state, since his step would sit hidden. Two writes carry
their own answer, and the server takes it (the write goes through, its reply says in one plain line what was changed, the call log counts it as a fix, see call_log.fixed):

  his-step-settled   the same write clears `needs` and hands the item to an agent (a mover, `agent`, or a line of `next` that opens with another session): his step is no longer waited on. It is marked
                     done only when exactly ONE step of his is open on the item (the said can then only be about it: the server does not compare the quote with the step's words, and this inference is the accepted trade-off) and the said this write stores holds a CHECKED Acked-by (the refusal carries what
                     the gate stored: `said`); else it is dropped, and with two or more open steps of his every step of his that leads `next` is dropped (a said cannot say which of them it is about, so
                     none is marked done) and the line says that his words are stored on the item. Said that is empty, unchecked or of another tag is no proof that he did the step, and the line says what was stored.
  step-none          the write passes step="none" (withdraw his step). The refusal text offered it as a way out, but it withdrew nothing where the item stores no step of its own: it now drops that line
                     (every step of his that leads `next`). Where the item does store a step or the your-step state, step="none" stays on the write, so that withdrawal happens as well.

The item is the one the refusal names (`gid`, the id the update normalized: board#N, #N, N and the store's own form all reach the same item). Only a step that is already on the item's checklist and open
can be marked, so a line this very write adds stays a refusal, as before. The write is made again with the mark added: a refused write stores nothing, so the first attempt left nothing to undo. When the
second attempt is refused too, the first refusal is the one the writer sees.

Imports point down only (the gate and the model beside it, the store's reader)."""
from __future__ import annotations

import inspect
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import call_log as _calls
from stackshot.core.instance import OWNER
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import said as _said
from stackshot.model import steps as _steps
from stackshot.service import gates as _gates
from stackshot.service.store import _load

NONE_WORDS = ("none", "clear", "-")      # what the write parameters read as "no value" (needs, step, mover, agent)
SETTLED = "his-step-settled"
NONE_APPLIED = "step-none-applied"


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def clears_needs(kw: dict[str, Any]) -> bool:
    """Does the write clear `needs` (clear_needs, needs="none" or an empty list) without setting a new list?"""
    needs = kw.get("needs")
    if isinstance(needs, list):
        return not needs
    return _text(needs).lower() in NONE_WORDS or (bool(kw.get("clear_needs")) and not _text(needs))


def hands_to_agent(kw: dict[str, Any], project: str = "") -> bool:
    """Does the write hand the item to an agent: a mover or `agent` that names a session (not him), or a line of `next` that opens with the name of a session the mover guard accepts (a mistyped opener
    hands the item to no one, so his step stays refused)?"""
    for k in ("mover", "post_wake_mover", "agent"):
        v = _text(kw.get(k))
        if v and v.lower() not in NONE_WORDS and not _model.is_owner(v):
            return True
    ctx = _mg.Ctx()
    return any((op := _steps.opener(ln)) and not _model.is_owner(op) and not ctx.mover_problem(op, project) for ln in _steps.split(_text(kw.get("next"))))


def _marks(v: Any) -> list[Any]:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def acked(entries: Any) -> bool:
    """Do the said entries the write stores hold a checked Acked-by of his (his words, read against his message)? An acted entry (Done-by), an unchecked one and any other tag do not."""
    return any(isinstance(e, dict) and e.get("tag") == _said.TAGS[0] and e.get("checked") and e.get("kind") != _said.ACTED for e in entries or ())


def _stored_said(entries: Any) -> str:
    """What the write stores as said, in words, for the line that says why a step was dropped."""
    got = [e for e in entries or () if isinstance(e, dict)]
    if not got:
        return "this write stores no said"
    if any(e.get("tag") == _said.TAGS[0] and e.get("kind") != _said.ACTED and not e.get("checked") for e in got):
        return "the said this write stores is an Acked-by that is unchecked (no transcript of the sender could be read here)"
    return "the said this write stores holds no Acked-by of his (" + ", ".join(sorted({str(e.get("tag") or "?") for e in got})) + ")"


def _leading(steps: list[dict[str, Any]], pos: int, skip: "set[int]" = frozenset()) -> list[int]:
    """The positions (0-based, on the checklist) of the open steps of his that lead `next` from the open step at `pos`: that one, and each open step after it as long as it is his too. A position in `skip`
    is a step the write itself drops or marks done: it is no longer in the way."""
    out = [pos]
    for i in range(pos + 1, len(steps)):
        if steps[i]["status"] != _steps.OPEN or i in skip:
            continue
        if not _steps.is_his(steps[i]["text"], unnamed_is_his=False):
            break
        out.append(i)
    return out


def _quoted(steps: list[dict[str, Any]], at: list[int]) -> str:
    return "; ".join(f"\"{_steps.first_line(steps[i]['text'])[:90]}\"" for i in at)


def settle(exc: "_gates.HisStepRefusal", kw: dict[str, Any]) -> "tuple[dict[str, Any], str, str] | None":
    """The write to make again for a refused write `kw` (every argument by name), with the kind of fix and the line that tells it; None when the refusal is none of the two kinds or the step is not an open
    step on the checklist of the item the refusal names."""
    gid = exc.gid
    withdraw = _text(kw.get("step")).lower() in NONE_WORDS and bool(_text(kw.get("step")))
    if not gid or not exc.line:
        return None
    try:
        item = _load(gid)
    except Exception:  # noqa: BLE001 — an item that cannot be read is no item to settle
        return None
    if item.get("status") != "open":
        return None
    meta = item.get("metadata") or {}
    settled = clears_needs(kw) and hands_to_agent(kw, str(meta.get("project") or "")) and not withdraw and not kw.get("done") and not kw.get("dropped")
    if not (settled or withdraw):
        return None
    steps = _steps.view(meta, keeper=str(meta.get("owner") or ""))
    want = _steps.first_line(exc.line)
    pos = next((i for i, s in enumerate(steps) if s["status"] == _steps.OPEN and _steps.first_line(s["text"]) == want), -1)
    if pos < 0:
        return None
    skip = {int(x) - 1 for x in (*_marks(kw.get("dropped")), *_marks(kw.get("done"))) if str(x).strip().isdigit()}
    lead = _leading(steps, pos, skip)
    shown = _quoted(steps, lead)
    many = len(lead) > 1
    what = f"steps {shown}" if many else f"step {shown}"
    if settled:
        his_open = sum(1 for s in steps if s["status"] == _steps.OPEN and _steps.is_his(s["text"], unnamed_is_his=False))
        if his_open == 1 and acked(exc.said):
            return ({**kw, "done": [pos + 1]}, SETTLED,
                    f"{OWNER}'s step {shown} was first in next while this write clears needs and hands the item to an agent, so it is marked done (a checked Acked-by of his is stored with this write, and it is his only open step)")
        why = (_stored_said(exc.said) if his_open == 1
               else f"he has {his_open} open steps, so no said can tell which one it is about" + (", and his words are stored on the item" if acked(exc.said) else f"; {_stored_said(exc.said)}"))
        note = (f"{OWNER}'s {what} {'were' if many else 'was'} first in next while this write clears needs and hands the item to an agent, so {'they are' if many else 'it is'} dropped ({why}, so nothing "
                f"records that he did {'them' if many else 'it'}); if {'they are' if many else 'it is'} still open, write {'them' if many else 'it'} again as {'lines' if many else 'a line'} of next")
        return {**kw, "dropped": [i + 1 for i in lead]}, SETTLED, note
    stored = meta.get("state") == "your-step" or bool(meta.get("step"))      # step="none" still has a stored step or state to withdraw: it stays on the write; else it would only be told as a no-op
    nkw = dict(kw) if stored else {k: v for k, v in kw.items() if k != "step"}
    return ({**nkw, "dropped": [*_marks(kw.get("dropped")), *[i + 1 for i in lead]]}, NONE_APPLIED,
            f"step=\"none\" dropped {OWNER}'s {what}, which {'were' if many else 'was'} first in next under an agent's state, so {'they are' if many else 'it is'} no longer {'his steps' if many else 'his step'}")


def run(exc: "_gates.HisStepRefusal", args: tuple[Any, ...], kw: dict[str, Any], again: Any) -> str:
    """Make the write again with its step settled (`again(*args, **kw)` is the update) and tell it; the refusal `exc` stands when there is nothing to settle or the second attempt is refused (the middleware
    then discards the fixes the refused call noted)."""
    try:
        named = dict(inspect.signature(again).bind(*args, **kw).arguments)      # the tool passes most arguments by position
    except TypeError:
        raise exc from None
    plan = settle(exc, named)
    if plan is None:
        raise exc
    kw2, kind, note = plan
    if kind == NONE_APPLIED:
        _calls.unfix("step-none")      # the no-op line the first attempt may have noted is no longer true
    try:
        out = again(**kw2)
    except ToolError:
        raise exc from None
    _calls.fixed(kind, note)
    return out
