"""machines_panel.py: what the board's Machines panel draws from the machine list a fleet manager posts (service/machines_list.py), and only while a fleet manager is paired.

`view(now)` answers None for a board that is not paired (`fleet/caller_keys.py` `paired()`: an approved key and a machine token), so such a board draws nothing from the list. For a paired board it answers
{"list": None} when there is no readable list yet, else

    {"list": True, "age": seconds since the server received the list, "stale": age > STALE_S, "received": epoch seconds,
     "machines": [{"name", "hostname", "letter", "roles": [..], "retired": bool, "detail": [one line of text per ssh / addresses / sources that is set]}, ...],
     "not_read": [file name, ...]}

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


def _machine(m: dict[str, Any]) -> dict[str, Any]:
    detail = []
    ssh = _text(m.get("ssh"))
    if ssh:
        detail.append("ssh: " + ssh)
    for key in ("addresses", "sources"):
        items = _texts(m.get(key))
        if items:
            detail.append(f"{key}: " + ", ".join(items))
    return {"name": _text(m.get("name")), "hostname": _text(m.get("hostname")), "letter": _text(m.get("letter")),
            "roles": [r for r in _texts(m.get("roles")) if r in _list.ROLES], "retired": m.get("retired") is True, "detail": detail}


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
                "machines": [_machine(m) for m in lst["machines"]], "not_read": _texts(lst["not_read"])}
    except Exception:       # a store or file that cannot be read: nothing to draw from it
        return None
