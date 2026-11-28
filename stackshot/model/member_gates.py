"""member_gates.py: what a write must name when the board has more than one member, and whom an item then asks.

With one member every item that waits on a member waits on that one, so a decision, a step of theirs or a `you:` line needs no name and none is asked for. With more than one, a write that leaves
an item waiting on a member without saying which is refused, and so is a `you:` line, which names nobody; an ask and a step on the same item must be for the same member. The check is a pure
function of the item's metadata as the write leaves it; with one member it returns at once, so such a board reads and writes as it always did.

A member is named on an item by its stored `mover`, by the first line of its `step`, or by a line of `next` that opens with the member's name or an alias.

Only the member an item asks answers it (asked_member, may_answer): the answer path (service/answer.py) and the pages that draw an answer form read the one rule here. While a question stands on an item
the home page lists it as the asked member's move (pick_of), a step beside it is finished by no other member (held_for), and the member that step is asked of sees the item wait for the pick (step_waits). And a record of an answer or a
note (metadata.answers) is the word of the member who made it, nobody else's (said_by): every reader that takes one as a person's answer, approval or note asks that here."""
from __future__ import annotations

import re
from typing import Any

from stackshot.core import members as _members
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import owner_steps as _os
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.needs import _needs_kinds


_YOU_RX = re.compile(r"[Yy]ou\s*:")          # the opener that names no member (members.opener_rx reads it as the first member's, so it is told apart here)


def listed() -> str:
    """The members' names for a refusal or a tool text: `Pat, Sam`."""
    return ", ".join(p.name for p in _members.members())


def many() -> bool:
    return len(_members.members()) > 1


def named_in(decide: Any) -> Any:
    """The member a Decide part names by its opener: `<name>:` or `<name> to …`, the name or an alias in any case; None when it opens with none (`you:` names nobody). The one reading of whom a
    question names, used for the member asked (asked_member) and for a stored record (partial)."""
    text = str(decide or "")
    if _YOU_RX.match(text.lstrip()):
        return None
    return _members.person_of(_steps.opener(text)) or _members.opener_person(text)


def asked_member(meta: dict[str, Any]) -> str:
    """The member the item's question is asked of: the one the ask's Decide part names (named_in), else the item's member (model.item_person)."""
    p = named_in(_os.decide_of(meta.get("ask")))
    return p.name if p else _model.item_person(meta).name


def may_answer(meta: dict[str, Any], member: str) -> bool:
    """Is what stands on the item asked of `member`, so that their answer counts? A question (a decision need with its ask or options, or with no step beside it) is asked_member's; else a your-step
    is every member's who has a part in it (steps.takes_part); an item that asks neither is its own member's (model.item_person). Always true with one member."""
    if not many():
        return True
    step = meta.get("state") == "your-step" and bool(_states.clean(meta.get("step")))
    if "decision" in _needs_kinds(meta) and (meta.get("ask") or meta.get("options") or not step):
        return member == asked_member(meta)
    return _steps.takes_part(meta, member) if step else member == _model.item_person(meta).name


def pick_of(meta: dict[str, Any]) -> str:
    """The member whose pick the item waits for, on a board of several members: asked_member while a question stands on it (a decision need with its ask or options), else ""."""
    if not many() or "decision" not in _needs_kinds(meta) or not (meta.get("ask") or meta.get("options")):
        return ""
    return asked_member(meta)


def held_for(meta: dict[str, Any]) -> str:
    """The member whose pick a your-step waits for: pick_of when that question stands beside the step, else "". No other member's Done on the step is taken until it is answered."""
    return pick_of(meta) if meta.get("state") == "your-step" and _states.clean(meta.get("step")) else ""


def step_waits(meta: dict[str, Any], member: str) -> bool:
    """Is the step asked of `member` (steps.member_for) held by a question asked of another member (held_for)? The item then waits, for them, on that member's pick."""
    return held_for(meta) not in ("", member) and member == _steps.member_for(meta.get("step"), meta)


def partial(rec: Any) -> bool:
    """Is the record `rec` of a board of several members a decision that settles nothing for the one asked: a Done or a note on a shared step by another member (the record names whose the step was,
    `asked`), or a decision on a question whose Decide part opens with another member's name? False for a comment, and always with one member."""
    if not many() or not isinstance(rec, dict) or rec.get("kind") == "comment":
        return False
    if rec.get("asked"):
        return True
    named = named_in(_os.decide_of(rec.get("ask")))
    return named is not None and not said_by(rec, named.name)


def said_by(rec: Any, member: str) -> bool:
    """Is the record `rec` (an entry of metadata.answers) the word of the member called `member`: made by them (members.recorded_by)? Always true with one member, whose every record is theirs."""
    return not many() or _model.names_member(_members.recorded_by(rec), member)


def owners(rec: Any) -> bool:
    """Is the record the owner's own word, the first member's (said_by)? What a rule reads as the owner's words or approval counts only such a record."""
    return said_by(rec, _members.first().name)


def you_lines(meta: dict[str, Any]) -> list[str]:
    """The lines of the item's step and next that open with `you:` (the opener that names no member)."""
    out = []
    for raw in [*str(meta.get("step") or "").splitlines()[:1], *_nl.split(meta.get("next"))]:
        ln = _states._MARK_RX.sub("", raw)
        if _YOU_RX.match(ln.lstrip()):
            out.append(ln.strip())
    return out


def gate_members(meta: dict[str, Any]) -> None:
    """Refuse a write that, on a board of several members, leaves a `you:` line, a decision or a step of a member's that names no member, or an ask and a step for two members."""
    if not many():
        return
    from fastmcp.exceptions import ToolError      # here, not at the top: the page renderer reads said_by from this module, and publish.py renders under the hooks' own Python, with no package installed
    names = listed()
    yl = you_lines(meta)
    if yl:
        raise ToolError(f"Refused: the line `{yl[0][:60]}` opens with `you:`, which names no member, and this board has several ({names}). Open it with the member's name, `{_members.first().name}: …`")
    asks = "decision" in _needs_kinds(meta)
    step = meta.get("state") == "your-step" or bool(str(meta.get("step") or "").strip())
    if not (asks or step):
        return
    named = _model.named_people(meta, meta.get("step"))
    what = "a decision" if asks and not step else "a step of a member's" if step and not asks else "a decision and a step"
    if not named:
        raise ToolError(f"Refused: this item waits on a member ({what}) and names none, and this board has several ({names}). Name the member: mover=<one of {names}>, or open the step's line "
                        f"or a line of next with the member's name (`{_members.first().name}: …`)")
    pair = _model.named_people({"mover": meta.get("mover")}, meta.get("step"))      # the ask is the mover's, the step is its own line's: a `<member>:` line of next about something else is no third claim
    if asks and step and len(pair) > 1:
        raise ToolError(f"Refused: the ask and the step of this item are for different members ({', '.join(p.name for p in pair)}). An ask beside a step names the same member: "
                        f"set mover=<one member> and open the step's line with that name")
