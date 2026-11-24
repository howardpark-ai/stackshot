"""front_turn.py: when a notice or a message may start a turn of a front agent.

A front agent is a session the person talks to. An inbound notice (the router's pass, a message with the person's mark) starts a turn of it in two cases only:
  1. it needs his attention and he is talking with that front agent now (`telling.present_fronts`: his last prompt in that pane is within [presence] minutes);
  2. he explicitly asked that front agent to tell him about the notice's subject.
Any other notice never reaches a front agent, not even held: the router sends it to the item's builder when it is about the builder's work, and otherwise logs it (ruling archived); a message that names an item of his is refused or routed the same way.
A message that carries the person's mark but names no open item of his (`his_items`) and none he asked that agent to tell him about (`asked`) is held for the agent's next turn and starts none: the mark is explicit, and an item is what it must point at.
The digest of lines queued while a pane was away (`messaging.digest_fyi`, from `inbox.take`) is asked the same: a turn only under these two cases, else its lines are filed as fyi lines and start none.

The record of case 2 is the item's own `tell_him` list (the update tool's `tell_him`): a front agent he asked to tell him about an item lists itself there. It is written only by a write that carries his own words (`said`,
checked against the transcript; gates.gate_tell_him), never by a session on its own say, and it is not `observers` (those hear a close or a reopen, and no entry of them is a request to be told). A notice matches the record by its
subject, an item it names, and by nothing else; a closed item no longer matches (but for the notice of its own close, which the item notices' gate asks with `closed`). Reading only: this module writes nothing.

Imports point down only: it reads the store and the model; `telling` is imported where used, because telling's gate reads this module too."""
from __future__ import annotations

import re
from typing import Iterable

from stackshot.anchors import anchors as _anc
from stackshot.model import model as _model
from stackshot.model.needs import _tell_him_of, _waits_decision
from stackshot.service.store import _load

_GID = re.compile(r"^[a-z]\d+$")


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
