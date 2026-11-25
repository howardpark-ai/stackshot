"""machines_panel.py: what the board's Machines panel takes from the machine list a fleet manager posts (service/machines_list.py), and only while a fleet manager is paired. The list chooses which machines get a card and in what
order (the page joins each to its own readings by name); it adds no card of its own and no text to a card.

`view(now)` answers None for a board that is not paired (`fleet/caller_keys.py` `paired()`: an approved key and a machine token), so such a board draws nothing from the list. For a paired board it answers
{"list": None} when there is no readable list yet, else

    {"list": True, "age": seconds since the server received the list, "stale": age > STALE_S, "received": epoch seconds,
     "machines": [{"name", "hostname", "retired": bool, "reported": {...}}, ...],
     "not_read": [file name, ...]}

`reported` is on a machine only when the posted entry carries at least one of the sender's four optional readings (`online`, `last_seen`, `versions`, `checked`; service/machines_list.py), so a list from a sender that sends none is
viewed exactly as before. It is {"online": bool | None, "last_seen": epoch s | None, "versions": {text: text} | None, "checked": epoch s | None, "fresh": bool}. None is unknown, never "no" or "off"; `versions` of {} is "the sender read nothing".
The readings are `fresh` only while the reading is no older than `STALE_S`: its age is how much older `checked` is than the post's own `written` (the sender's clock against itself) plus the age of the list on the server's clock
(`age` above); an entry with no usable `checked` is never fresh. A reading that is not fresh is viewed as unknown (online, last_seen and versions None), so no reader can take it for a fact; `checked` stays for display.

The page does not draw `reported` yet: the cards show only the board's own readings. `fallback(own, reported)` is the rule for the day it does, field by field: the board's own reading wins wherever it has one, and the sender's is used
only where the own one is missing and `reported` is fresh.

The age is the server's own clock at the post (`received`), never the sender's `written`, which a wrong clock on the sender would make wrong. A list is stale once it is older than `STALE_S`: the sender posts when
the list changes and at least every few minutes, so a quarter of an hour of silence is a sender that stopped; the list is still shown, with its age.

Every value is plain text, as stored and not escaped: the caller (the page) escapes each one where it draws it and builds no link, command or markup from one. The stored file is read as a list but its fields are
not checked again on the way back, so a hand-edited file may hold any JSON: each field is taken as text only when it is text (a list of text only when it is one) and is left out otherwise, so a field of the wrong
kind draws as nothing instead of breaking the page.

A service module: it imports core, the domain's key store and the list's module, and the standard library."""
from __future__ import annotations

from typing import Any

from stackshot.fleet import caller_keys as _keys
from stackshot.service import machines_list as _list

STALE_S = 900.0     # a list older than this (seconds since it was received) is drawn with a stale mark; it is still drawn
NOT_READ_SHOWN = 20     # the panel names at most this many of `not_read`, then how many more


def _text(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _texts(v: Any) -> list[str]:
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


def _time(v: Any) -> float | None:
    """A stored time as a number: a finite number of 0 to the list's bound that is no bool, else None (a hand-edited file may hold anything)."""
    n = _list._num(v)
    return n if n is not None and n >= 0 else None


def _versions(v: Any) -> dict[str, str] | None:
    """The stored `versions` as a dict of text to text within the list's entry limit, else None (unknown): a dict that breaks one is not trusted in part."""
    if not isinstance(v, dict) or len(v) > _list.VERSIONS_MAX or not all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()):
        return None
    return dict(v)


def _reported(m: dict[str, Any], written: float, age: float) -> dict[str, Any] | None:
    """The sender's readings of one machine as the module's text describes them, None when the entry carries none of the four keys. `written` is the list's, `age` the list's age on the server's clock."""
    if not any(k in m for k in _list.READING_KEYS):
        return None
    checked = _time(m.get("checked"))
    fresh = checked is not None and age + max(0.0, written - checked) <= STALE_S
    online = m.get("online") if isinstance(m.get("online"), bool) else None
    return {"online": online if fresh else None, "last_seen": _time(m.get("last_seen")) if fresh else None,
            "versions": _versions(m.get("versions")) if fresh else None, "checked": checked, "fresh": fresh}


def _machine(m: dict[str, Any], written: float, age: float) -> dict[str, Any]:
    out: dict[str, Any] = {"name": _text(m.get("name")), "hostname": _text(m.get("hostname")), "retired": m.get("retired") is True}
    rep = _reported(m, written, age)
    if rep is not None:
        out["reported"] = rep
    return out


def fallback(own: dict[str, Any] | None, reported: dict[str, Any] | None) -> dict[str, Any]:
    """The reading to show for each of `online`, `last_seen` and `versions`, field by field: {field: {"value", "source"}}. Source "own": the board's own reading, which wins wherever it has one (not None). Source "list": the
    sender's, only where the own reading is None and `reported` is fresh and has a value for the field. Otherwise (None, None): unknown. `own` maps a field to the board's reading, None or left out for none. Nothing draws this yet."""
    out: dict[str, Any] = {}
    fresh = isinstance(reported, dict) and reported.get("fresh") is True
    for key in ("online", "last_seen", "versions"):
        mine = (own or {}).get(key)
        theirs = reported.get(key) if fresh else None
        if mine is not None:
            out[key] = {"value": mine, "source": "own"}
        elif theirs is not None:
            out[key] = {"value": theirs, "source": "list"}
        else:
            out[key] = {"value": None, "source": None}
    return out


def view(now: float) -> dict[str, Any] | None:
    """What the Machines panel draws from the list at time `now` (epoch seconds): None when no fleet manager is paired; {"list": None} when paired and no list can be read; else the list as the module's text describes.
    Never raises."""
    try:
        if not _keys.paired():
            return None
        got = _list.last_machines()
        if got is None:
            return {"list": None}
        lst, received = got
        age = max(0.0, now - received)
        return {"list": True, "age": age, "stale": age > STALE_S, "received": received,
                "machines": [_machine(m, lst["written"], age) for m in lst["machines"]], "not_read": _texts(lst["not_read"])}
    except Exception:       # a store or file that cannot be read: nothing to draw from it
        return None
