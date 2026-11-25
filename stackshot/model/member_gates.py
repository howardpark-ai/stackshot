"""member_gates.py: what a write must name when the board has more than one member.

With one member every item that waits on a member waits on that one, so a decision, a step of theirs or a `you:` line needs no name and none is asked for. With more than one, a write that leaves
an item waiting on a member without saying which is refused, and so is a `you:` line, which names nobody; an ask and a step on the same item must be for the same member. The check is a pure
function of the item's metadata as the write leaves it; with one member it returns at once, so such a board reads and writes as it always did.

A member is named on an item by its stored `mover`, by the first line of its `step`, or by a line of `next` that opens with the member's name or an alias."""
from __future__ import annotations

import re
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import members as _members
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import states as _states
from stackshot.model.needs import _needs_kinds


_YOU_RX = re.compile(r"[Yy]ou\s*:")          # the opener that names no member (members.opener_rx reads it as the first member's, so it is told apart here)


def listed() -> str:
    """The members' names for a refusal or a tool text: `Pat, Sam`."""
    return ", ".join(p.name for p in _members.members())


def many() -> bool:
    return len(_members.members()) > 1


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
