"""front_turn.py: when a notice or a message may start a turn of a front agent.

A front agent is a session the person talks to. An inbound notice (the router's pass, a message with the person's mark) starts a turn of it in two cases only:
  1. it needs his attention and he is talking with that front agent now (`telling.present_fronts`: his last prompt in that pane is within [presence] minutes);
  2. he explicitly asked that front agent to tell him about the notice's subject.
Any other notice never reaches a front agent, not even held: the router sends it to the item's builder when it is about the builder's work, and otherwise logs it (ruling archived); a message that names an item of his, marked for him, is written onto the item (or held for the agent's next turn when no item can take it) and starts no turn.
A message that carries the person's mark but names no open item of his (`his_items`) and none he asked that agent to tell him about (`asked`) is held for the agent's next turn and starts none: the mark is explicit, and an item is what it must point at.
The digest of lines queued for a pane (`messaging.digest_fyi`, from `inbox.take`) is asked the same: a turn only under these two cases, else its lines are filed as fyi lines and start none.
One more case, off until an instance names the agent: `[front] result_turn_agents` lists front agents to which a session that was handed work by them (a message of theirs that reached it within `[front] result_turn_hours`, or an open item the session moves that the agent itself handed it: the item's hand-off record names the agent as the sender and the session as the new mover) may write the result and start a turn, whether or not he is there
(`messaging.handed_to`, `messaging.router_result`; the reader of the three keys is here: `result_turn_agents`, `result_turn_hours`, `result_turn_cap_per_hour`). Such a line is stored with the kind `exempt`, so the digest never files it. It is no case of `warranted`: the message tool and the router decide it before they ask this module.

The record of case 2 is the item's own `tell_him` list (the update tool's `tell_him`): a front agent he asked to tell him about an item lists itself there. It is written only by a write that carries his own words (`said`,
checked against the transcript; gates.gate_tell_him), never by a session on its own say, and it is not `observers` (those hear a close or a reopen, and no entry of them is a request to be told). A notice matches the record by its
subject, an item it names, and by nothing else; a closed item no longer matches (but for the notice of its own close, which the item notices' gate asks with `closed`). Reading only: this module writes nothing.

Imports point down only: it reads the store and the model; `telling` is imported where used, because telling's gate reads this module too."""
from __future__ import annotations

import math
import re
from typing import Iterable

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.model.needs import _tell_him_of, _waits_decision
from stackshot.service.store import _load

_GID = re.compile(r"^[a-z]\d+$")

RESULT_TURN_HOURS = 24         # a message of the front agent to a session counts as a hand-over of work for this long
RESULT_TURN_CAP_PER_HOUR = 6   # the most result turns one session may start in one front agent in an hour


def result_turn_agents() -> list[str]:
    """`[front] result_turn_agents`: the front agents a session they handed work to may start a turn of with its result (names, case-folded). [] when the key is missing, is no list, or holds no name: nothing changes for the instance."""
    raw = _cfg.get("front", "result_turn_agents", default=[])
    return [str(x).strip().casefold() for x in raw if isinstance(x, str) and str(x).strip()] if isinstance(raw, list) else []


def result_turn_hours() -> float:
    """`[front] result_turn_hours` (24 by default): how long after a message of the front agent to a session that session's reply may start a turn. A value that is no finite number above 0 (a boolean, a string, nan, inf, an integer too large for a float) reads as 24 (`config.notes` says so)."""
    raw = _cfg.get("front", "result_turn_hours", default=RESULT_TURN_HOURS)
    try:
        v = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0
        return v if math.isfinite(v) and v > 0 else float(RESULT_TURN_HOURS)
    except (TypeError, ValueError, ArithmeticError):      # OverflowError: an integer of hundreds of digits
        return float(RESULT_TURN_HOURS)


def result_turn_cap_per_hour() -> int:
    """`[front] result_turn_cap_per_hour` (6 by default): the most turns one sender may start in one listed front agent in an hour; past it a message is held as it is without the key (the loop stop). 0 turns the case off. A value that is no whole number from 0 reads as 6."""
    raw = _cfg.get("front", "result_turn_cap_per_hour", default=RESULT_TURN_CAP_PER_HOUR)
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else RESULT_TURN_CAP_PER_HOUR


def _gids(subject: Iterable[str] | str) -> list[str]:
    """The item ids of a subject (a list, or a comma or space separated string): only the store's own spelling, a letter and digits."""
    parts = re.split(r"[,\s]+", subject) if isinstance(subject, str) else [str(x) for x in subject]
    return [p for p in parts if _GID.match(p)]


def present(agent: str) -> bool:
    """Case 1's half: is he talking with this front agent now (telling.present_fronts)? False on any failure: no presence, no turn."""
    try:
        from stackshot.service import telling as _telling
        return any(_anc.same_session(agent, name) for name in _telling.present_fronts())
    except Exception:  # noqa: BLE001
        return False


def asked(agent: str, subject: Iterable[str] | str, closed: bool = False) -> bool:
    """Case 2: did he ask this front agent to tell him about the subject: is the agent listed in the `tell_him` of an open item the subject names? A completed item no longer matches, unless `closed`: the
    notice is about that item's own close (it is saved as completed before its observers are told). False on any failure."""
    for gid in _gids(subject):
        try:
            it = _load(gid)
            if it.get("status") == "completed" and not closed:
                continue
            if any(_anc.same_session(agent, ob) for ob in _tell_him_of(it.get("metadata") or {})):
                return True
        except Exception:  # noqa: BLE001  — an unreadable item records no ask
            continue
    return False


def warranted(agent: str, subject: Iterable[str] | str = (), needs: bool = True) -> bool:
    """May a notice about `subject` start a turn of the front agent `agent`: case 2 (asked), or case 1 (`needs` him and he is there: present)? `needs` is the caller's own test of whether the notice needs him."""
    return asked(agent, subject) or (bool(needs) and present(agent))


def his_items(subject: Iterable[str] | str) -> list[str]:
    """The open items the subject names that are his to act on: needs holds `decision` (read first, from the item alone), or the model reads him as the one who moves the item (your-call, your-step) or, on a parked one,
    picks it up when the wait ends (a park with him as the mover). The model's mover decides, not needs alone: an item whose needs lost `decision` but whose mover is still him counts. [] when none. Fails closed: an item
    that cannot be read counts as none (an exception never reaches the caller), so a notice that depends on this finds nothing and is held, never delivered on a guess. A model that cannot be derived hides no plain
    `needs: decision` item."""
    out: list[str] = []
    for gid in _gids(subject):
        try:
            it = _load(gid)
            if it.get("status") != "open":
                continue
            if _waits_decision(it.get("metadata") or {}):
                out.append(gid)
                continue
        except Exception:  # noqa: BLE001  — an unreadable item is no item of his
            continue
        try:
            from stackshot.service import item_read as _item_read
            mod = _item_read._model_of({**it, "gid": gid})
            if mod.owner_moves or (mod.state == _model.WAITING and mod.wait is not None and _model.is_owner(mod.picker)):
                out.append(gid)
        except Exception:  # noqa: BLE001  — a model that cannot be derived: no step of his is found, the decision test above stood alone
            continue
    return out


def names_his(agent: str, subject: Iterable[str] | str) -> bool:
    """Does the subject name an item a marked message to the front agent `agent` may point at: an open item of his (`his_items`), or one he asked that agent to tell him about (`asked`: the agent is in its `tell_him`, though
    the item is moved by a builder and waits on no decision of his)? False on any failure: nothing is named on a guess."""
    try:
        gids = _gids(subject)
        return bool(his_items(gids) or asked(agent, gids))
    except Exception:  # noqa: BLE001
        return False
