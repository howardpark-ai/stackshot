"""contact.py — an item's contact: the front agent the person the board is for talks to about the item.

An item stores it as `metadata.contact`, the session by its permanent id where the fleet registry resolves it (a rename then changes nothing stored), else by the name it was given.
The item page's side column leads with it ("Owner"), linked to its session. It is a filing field: setting it moves no state clock, changes no mover and sends no notice (an update that sets it still moves `updated`, as any write does).

Who is the contact:
  - an item created by a front agent (a user-facing agent: the sessions the person talks to): that agent;
  - an item created by a background agent: the front agent the creator names, one of the project's front agents (the server lists them with their mandates and refuses any other
    name), else the project's -main agent;
  - when the contact retires, or the item moves to another project, it falls to the project's -main agent (server.py `_contact_fall_retired`, `_contact_after_move` in service/update.py);
  - every open item without one is given one by `tools/backfill_contact.py` (the creator when that was a front agent, else the project's -main).

Why `contact` and not `owner`: `owner` is a retired term (tests/retired_terms.toml: it once meant the item's mover, then the keeper of record), `metadata.owner` is still the stored
creator, and the deprecated `owner` parameter of create and update is accepted until [model] owner_param_until. A second meaning for the same key or the same word would make every old
reader and every old session read the wrong thing. `contact` is free, and says what the person does with it.

Pure rules here, no item store: the server (server.py) reads the registry and the sessions and calls these. Imports anchors.py (the page registry) and projects.py (agents only the
record holds), both stdlib only."""
from __future__ import annotations

import re
from typing import Any, Callable

from stackshot.anchors import anchors as _anc

MANDATE_MAX = 160
KEY = "contact"
NONE_WORDS = {"", "none", "clear", "-", "null"}

# the rules the backfill reports its counts by
RULE_HAS = "has_contact"              # an open item that has a live contact: left as it is
RULE_CREATOR = "creator_front"        # no contact; the creator was a front agent: the creator
RULE_MAIN = "main"                    # no contact; the creator was not a front agent: the project's -main agent
RULE_RETIRED = "retired_contact"      # a contact that is no front agent any more: the project's -main agent
RULE_NO_MAIN = "no_main"              # the project names no -main agent: left without a contact
RULE_CLOSED = "closed"                # a closed item is a record: left as it is
RULES = (RULE_CREATOR, RULE_MAIN, RULE_RETIRED, RULE_HAS, RULE_NO_MAIN, RULE_CLOSED)


def _one_line(text: Any, limit: int = MANDATE_MAX) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + " …"


def fronts(project: str, reg: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
    """The user-facing agents of an item's project → {name: mandate line, one line}: the `agents:` entries outside `background:` of the project's page, of its top-level page and of its
    hub, as server._hub_sessions reads them, and the agents only the project record holds (their page line still owed, projects.with_pending). {} when the project names none."""
    from stackshot.projects import projects as _prj
    reg = _prj.with_pending(_anc.registry() if reg is None else reg, made=True)
    key = str(project or "").strip().strip("/")
    keys = [k for k in dict.fromkeys([key, _anc.pilot_root(key), _anc.hub_of(key, reg)]) if k]
    back: set[str] = set()
    for k in keys:
        back |= {str(x) for x in ((reg.get(k) or {}).get("back_agents") or {})}
    out: dict[str, str] = {}
    for k in keys:
        for n, m in ((reg.get(k) or {}).get("agents") or {}).items():
            if str(n) not in back and str(n) not in out:
                out[str(n)] = _one_line(m)
    return out


def listing(choices: dict[str, str]) -> str:
    """The front agents as a refusal or a reply names them: `name (mandate); name (mandate)`; "none listed" when there are none."""
    return "; ".join(f"{n} ({m})" if m else n for n, m in choices.items()) or "none listed"


def refusal(name: str, project: str, choices: dict[str, str], main: str = "") -> str:
    """The text of a refused contact: the name is no front agent of the project; the allowed ones, each with its mandate."""
    if not choices:
        return (f"Refused: contact={name} is not a front agent of {project}, and the project lists none of its own"
                + (f" (its -main agent is {main}: leave contact out and it is the contact)" if main else "") + ".")
    return (f"Refused: contact={name} is not a front agent (a user-facing agent) of {project}. A contact is the front agent the item's person talks to about it; "
            f"{project}'s are: {listing(choices)}." + (f" Leave contact out and it is {main}." if main else ""))


def plan(item: dict[str, Any], *, creator_front: bool, main: str, alive: Callable[[str], bool]) -> tuple[str, str]:
    """What the backfill does with one item → (the contact to store, "" for no change; the rule it falls under, one of RULES).
    `creator_front`: the item's creator is a front agent; `main`: the item's project's -main agent ("" when none); `alive(contact)`: the stored contact is still a front agent."""
    if item.get("status") != "open":
        return "", RULE_CLOSED
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    have = str(meta.get(KEY) or "").strip()
    if have and alive(have):
        return "", RULE_HAS
    if have:                                    # stored, but no front agent any more (it retired, or never was one)
        return (main, RULE_RETIRED) if main else ("", RULE_NO_MAIN)
    creator = str(meta.get("owner") or "").strip()
    if creator and creator_front:
        return creator, RULE_CREATOR
    return (main, RULE_MAIN) if main else ("", RULE_NO_MAIN)
