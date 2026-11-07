"""retire_fields.py — the data change that takes the stored state words and their carry fields out of an open item's storage. Pure functions of an item's metadata, its description and the clock: no server
import, so the server's retire pass (server._retire_one), tools/retire_fields_report.py and the tests share one copy.

What an open item stores of the old model, and where the value goes (the alive/waiting reading of the item does not change: the server refuses an item whose reading would):

  state            dropped (the seven state words; `queued` is a different mechanism and stays). The word an item reads as is derived from its fields (states.derive).
  party, chase, end  copied into the home that already exists, when that home is empty (the readers that show a party or a chase read the home when the field is empty: the model and the relay's text, and, since the retire pass, the router's item list and the cold call, which take wait_event and ask_by then) (party → wait_event, chase → ask_by, end → wake), then dropped.
                   Except on an item that stores a wait_kind (the watchers watch it): the relay's ask names the party from `party` (watchers.subject_of) and a chase day copied into ask_by would start a backstop the
                   item never had, so its party is HELD, and its chase too when ask_by is empty.
                   On any item a party the wait_event does not already name (the relay's ask reads "a reply from <party>"), and a chase day the ask_by does not start with, are HELD too: the home is full with
                   something else, and a reader takes the home only when the field is empty, so dropping the field would make it show the other text. An end beside a wake is dropped (the wake wins in every reader).
                   A verifying item's end day (YYYY-MM-DD, the state's wait to the END of that day) becomes the wake `<day>T23:59`, the last minute a wake can name.
  proof (verifying)  a verifying item keeps waiting without its state word: its proof becomes the text of a wait_basis on its wake (waiting.basis_of reads it for that very wake), then the proof is dropped.
  supplies         one line, what another item's output gives this one: it moves into the description as a "- Needs: …" bullet (kept when the description already says it), then the field is dropped. When the
                   description with the bullet would break a limit (`fits` says: [description] max_lines, line_max), the supplies are HELD: the field stays and the description is not touched.
  expected_by, expected_reason  retired already (a write drops them and stores nothing): dropped.
  step             the step of a your-step item stands on the stored state; such an item is held back (state and step stay) until the write path stores the step another way. A step on any other
                   item has no home: held back too. Both are listed, never dropped.
  wait_kind        stays: it is part of the new model (the watchers' watched set), not an old field.

`plan_for` answers {"edits": {key: new value, None = drop}, "description": the new description or None (unchanged), "held": [fields left and why], "moved": {home: value}}; `{}` edits = nothing to do.
`apply_edits` and `entry_for` build the new item and the undo entry (before and after of exactly the keys the plan touched)."""
from __future__ import annotations

import copy
from typing import Any, Callable
import re

STATE_WORDS = ("doing", "your-call", "your-step", "outside", "blocked", "parked", "verifying")      # the seven (states.STATES); `queued` is read as doing and belongs to the rank queue
MOVES = {"party": "wait_event", "chase": "ask_by", "end": "wake"}       # carry field → the home the readers already fall back to (model.derive)
DROPPED = ("expected_by", "expected_reason")                            # retired already: nothing reads them
NEEDS_PREFIX = "- Needs: "
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
END_OF_DAY = "T23:59"          # the last minute a wake can name: a verifying item's end day becomes a wake at the end of that day
ENTRY_KEYS = frozenset({"state", "party", "chase", "end", "proof", "supplies", "step", "expected_by", "expected_reason", "wait_event", "ask_by", "wake", "wait_basis", "description"})      # what an undo entry may name


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def empty(v: Any) -> bool:
    return v is None or v == "" or v == {} or v == []


def stored_word(meta: dict[str, Any]) -> str:
    v = meta.get("state")
    return v if isinstance(v, str) and v in STATE_WORDS else ""


def names(home: Any, value: Any) -> bool:
    """Does the text already in a home say the value (the party in the wait_event, the chase day at the start of ask_by)? Compared whole words apart from case and spacing."""
    h, v = clean(home).lower(), clean(value).lower()
    return bool(v) and (h == v or h.startswith(v) or v in h)


def needs_bullet(supplies: Any) -> str:
    return NEEDS_PREFIX + clean(supplies)


def add_needs(description: str, supplies: Any) -> str:
    """The description with the supplies line as a "- Needs: …" bullet at the end, unchanged when the line (or its text) is already there."""
    text = clean(supplies)
    if not text or text.lower() in clean(description).lower():
        return description
    base = (description or "").rstrip("\n")
    return (base + "\n" if base else "") + needs_bullet(text) + ("\n" if (description or "").endswith("\n") else "")


def plan_for(meta: dict[str, Any], description: str = "", now: float = 0.0, fits: Callable[[str], str] | None = None) -> dict[str, Any]:
    """The plan for one open item. `edits` = {metadata key: new value}, None drops the key. `description` = the description with the Needs bullet, None when it does not change. `held` = [(field, why)]
    for a field the plan leaves. `moved` = {home: value} for the values copied into a home. `fits(description)` = "" when a description is within the limits, else why not: the supplies stay (held) when the
    Needs bullet would break one. Pure."""
    edits: dict[str, Any] = {}
    moved: dict[str, Any] = {}
    held: list[tuple[str, str]] = []
    new_desc: str | None = None
    word = stored_word(meta)
    step_here = not empty(meta.get("step"))
    if word == "your-step" or step_here:
        held.append(("step", "the step stands on the stored state (your-step); the item is left as it is" if word == "your-step" else "a step with no your-step state has no home"))
        if word == "your-step":
            return {"edits": {}, "description": None, "held": held, "moved": {}}
    if word:
        edits["state"] = None
    watched = not empty(meta.get("wait_kind"))
    for f, home in MOVES.items():
        v = meta.get(f)
        if empty(v):
            continue
        if watched and (f == "party" or (f == "chase" and empty(meta.get(home)))):
            held.append((f, "the watchers read it (the relay's ask names the party; a chase copied into ask_by would start a backstop)"))
            continue
        if f != "end" and not empty(meta.get(home)) and not names(meta.get(home), v):
            held.append((f, f"{home} is set already and does not say it (a reader takes {home} only when {f} is empty, so dropping {f} would change what it shows)"))
            continue
        if empty(meta.get(home)):
            if f == "end" and word == "verifying" and DAY.match(str(v).strip()):
                v = str(v).strip() + END_OF_DAY      # the end day stands as a wait to the END of that day, as the verifying state read it
            edits[home] = v
            moved[home] = v
        edits[f] = None
    wake = edits.get("wake") if edits.get("wake") is not None else meta.get("wake")
    proof = clean(meta.get("proof"))
    if proof:
        if word == "verifying" and wake and empty(meta.get("wait_basis")):
            edits["wait_basis"] = {"text": proof, "wake": wake, "by": "migration", "at": now}
            edits["proof"] = None
        else:
            held.append(("proof", "a proof outside a verifying item with an end day has no home"))
    supplies = clean(meta.get("supplies"))
    if supplies:
        new_desc = add_needs(description, supplies)
        problem = fits(new_desc) if fits is not None and new_desc != description else ""
        if problem:
            held.append(("supplies", f"the description with the Needs bullet would break its limit ({problem}); the line stays in supplies"))
            new_desc = None
        else:
            edits["supplies"] = None
    for f in DROPPED:
        if not empty(meta.get(f)):
            edits[f] = None
    if new_desc == description:
        new_desc = None
    edits = {k: v for k, v in edits.items() if not (v is None and k not in meta)}
    return {"edits": edits, "description": new_desc, "held": held, "moved": moved}


def apply_edits(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """A copy of the item with the plan applied."""
    out = copy.deepcopy(item)
    meta = out.setdefault("metadata", {})
    for k, v in plan["edits"].items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    if plan["description"] is not None:
        out["description"] = plan["description"]
    return out


def keys_of(plan: dict[str, Any]) -> list[str]:
    return [*plan["edits"], *(["description"] if plan["description"] is not None else [])]


def snapshot(item: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """The values `keys` hold on the item (a metadata key or `description`), None = absent."""
    meta = item.get("metadata") or {}
    return {k: (item.get("description") if k == "description" else meta.get(k)) for k in keys}


def entry_for(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The undo entry's two sides: {"before": {key: value}, "after": {key: value}} for exactly the keys the plan touches."""
    keys = keys_of(plan)
    return {"before": snapshot(item, keys), "after": snapshot(apply_edits(item, plan), keys)}


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one a retire writes ("" = fine): an object whose keys are all in ENTRY_KEYS."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass touched"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the retire pass writes" if extra else ""
