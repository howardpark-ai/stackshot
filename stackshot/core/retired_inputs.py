"""retired_inputs.py — the old item-state inputs of the create and update tools and of the client API, and the refusal a caller that still passes one gets.

An item stores alive or waiting directly now (the item model: docs/design), so the inputs that moved an item between the seven old state words no longer exist:

  state, clear_state   the word an item stood in, and its removal
  party, chase, end    what a state carried: who is waited on, the day to chase, the end day of a check
  proof                what proves a checked item works
  chase_note           one logged follow-up on a relay or anchor wait

They are gone from the tools' signatures, so a client's cached schema could still send one; the server's middleware (web/middleware.py _RetiredInputs) reads the call's arguments before the tool does and refuses
one with a ToolError that names what to pass instead. A call is never silently let through and never reaches the tool's own argument check (which would answer with a bare "unexpected argument").
`step` and `supplies` are not here: they have no home in the new model yet and stay as they were.

Pure: no server import, so the middleware, the client API's route, client.py and the tests share one copy of the words."""
from __future__ import annotations

from typing import Any

RETIRED = ("state", "clear_state", "chase", "chase_note", "party", "end", "proof")     # the input names, in the order the refusal lists them
TOOLS = ("create", "update")                                                          # the tools whose arguments are read

_STATE_WORDS = {
    "doing": "work in hand needs no word: say whose move it is with mover=<a session, the project's builder or {owner}> and keep an open step in next",
    "your-call": "needs=[\"decision\"] with ask=<the ask line> asks {owner}",
    "your-step": "step=<one line, no command> with mover={owner} (what he runs goes in a next line that starts `{owner}:`)",
    "outside": "wait_kind=\"relay\" with wait_event=<who or what is waited on>, ask_by=<the day to chase, YYYY-MM-DD> and post_wake_mover=<who takes it then> (and needs=[\"external\"])",
    "blocked": "after=[\"board#N\"] names the item it waits on, with ask_by=<the day to look again, YYYY-MM-DD> (supplies=<one line: what that item gives this one> says what it takes from it)",
    "parked": "hold=true with wake=<YYYY-MM-DD or YYYY-MM-DDTHH:MM> and wait_basis=<what it waits for, with its date YYYY-MM-DD>",
    "verifying": "wake=<the day the check ends> with wait_basis=<what it waits for, with its date YYYY-MM-DD>, and mover=<the session that checks>",
    "queued": "a builder starts every item handed to it at its next turn: mover=<the builder>",
    "none": "no state is stored, so there is none to clear: drop a stored wait with clear_wait=true",
}
_FIELD_HOW = {
    "clear_state": "there is no state to clear: an item stores alive or waiting directly, so drop what it waits on instead (clear_wait=true for a stored wait, clear_wake=true, clear_hold=true, clear_after=true; step=\"none\" for his step)",
    "chase": "ask_by=YYYY-MM-DD is the day to chase, on a relay wait (wait_kind=\"relay\", wait_event=<who or what is waited on>, post_wake_mover=<who takes it then>)",
    "chase_note": "a chase is no longer logged by hand: a relay or anchor wait comes back to its mover on its ask_by day, so move ask_by to chase later",
    "party": "wait_event=<who or what is waited on>, with wait_kind=\"relay\" (news only {owner} relays) or \"anchor\" (an event at an anchor)",
    "end": "wake=<YYYY-MM-DD or YYYY-MM-DDTHH:MM> with wait_basis=<what it waits for, with its date YYYY-MM-DD>: the end day of a check is a time wait",
    "proof": "wait_basis=<what it waits for, with its date YYYY-MM-DD> on the wake, or write what proves it works as the next step",
}


def given(value: Any) -> bool:
    """Is this a value the caller passed on purpose? A cached schema of a client that fills every parameter with its default sends "", false or null: that is no call to refuse."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple)):
        return bool(value)
    return True


def passed(arguments: Any) -> list[str]:
    """The retired inputs a call's arguments carry, in RETIRED's order."""
    if not isinstance(arguments, dict):
        return []
    return [k for k in RETIRED if given(arguments.get(k))]


def refusal(arguments: Any, owner: str = "the owner") -> str:
    """"" when the call passes no retired input, else the refusal naming what to pass instead (one line per input, the state's own word answered by what it said). Nothing has been written."""
    names = passed(arguments)
    if not names:
        return ""
    args = arguments if isinstance(arguments, dict) else {}
    lines: list[str] = []
    for k in names:
        if k == "state":
            word = str(args.get("state") or "").strip().lower()
            how = _STATE_WORDS.get(word) or ("alive or waiting is stored directly: whose move it is with mover=<who>; a park with hold=true, wake and wait_basis; a wait on another item with after=[\"board#N\"]; "
                                             "a wait on something outside with wait_kind, wait_event, ask_by and post_wake_mover; {owner}'s call with needs=[\"decision\"] and ask")
            lines.append(f"state={word or '…'}: {how}")
        else:
            lines.append(f"{k}: {_FIELD_HOW[k]}")
    head = (f"Refused: {', '.join(names)} {'is a retired input' if len(names) == 1 else 'are retired inputs'} of update and create: an item stores alive or waiting directly now "
            "(the item model: docs/design), so there is no state to set and no field a state carried. Nothing was written. Instead: ")
    return (head + "; ".join(lines) + ".").replace("{owner}", owner)


def client_refusal(owner: str = "the owner") -> str:
    """The answer of POST /client/state, a route that only set or cleared a state."""
    return ("Refused: POST /client/state is retired: an item stores alive or waiting directly now, so a script has no state to set or clear (the item model: docs/design). "
            "Pass the fields that say it through update: mover=<who moves it>, hold=true with wake and wait_basis for a park, after=[\"board#N\"] for another item, "
            f"wait_kind with wait_event, ask_by and post_wake_mover for a wait on something outside, needs=[\"decision\"] with ask for {owner}'s call.")
