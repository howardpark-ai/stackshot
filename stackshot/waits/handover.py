"""handover.py: a finished step reaches the session the next step names, by the system, not by whoever remembers.

A step is done (ticked by its proof, or marked by hand) and the next open step opens with another session: the item's mover becomes that session and it is told, with the step's text. The notice of
a ticked step goes to the item's mover; the session named on the next step is told by this module. This module decides; the item is written and the session told by the server
(`proofs.handover` (service/proofs.py), called by `proofs.proof_item` and by `update` when it marks a step done), and the audit reads the record it leaves (`audit_checks.check_step_handover`).

  next_open(meta, keeper)                      (text, opener) of the first open step that is not a bare sub-step: the step whose session is next
  decide(meta, keeper, mover, kind_of, down_of, same)   {"action": move | fallback | none, "to", "step", "hash", "why"}
  mark(meta, h, kind, to, at, why)             the record, `metadata.handover` = {"step": <hash>, "kind": moved | fallback, "to", "at"[, "why"]}; one record, the last step handled
  skip_reason(meta, mover, same, label, owner)   why the hand-over leaves an item alone: on hold, a decision wait, needs naming another session (the server and the audit share it)
  fresh(before, after)                         the record after a write when it is new or changed: the History's `step hand-over: …` line
  handled(meta, h, kind)                       was the step with hash `h` handed over (kind "moved") or fallen back on (kind "fallback") already?

The first open step decides, in the checklist's order: several open steps are several sessions' turns, each handed over in its turn when the one before is done. The rules, in this order:
  - no open step, a step that names no one, or one that names the item's mover: nothing to do;
  - the owner (his step is his; the system never moves an item to him), a front agent or a retired session (the front-step rule of front_step.py moves its step on, and no item notice wakes a front agent),
    a name that is no session of the fleet: nothing is moved;
  - a session that is down or unknown (no pane, its last turn ended in an error): the item stays with its mover, who is told the step and why ("fallback"); the step is never lost;
  - otherwise the mover becomes that session ("move").
Idempotent: a step already handed over (kind "moved") is not handled again, and one that fell back is told once; it is handled again only when the session can be reached.
Pure functions of strings and metadata: no server import."""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from stackshot.model import steps as _steps

KEY = "handover"
SESSION, FRONT, OWNER, OTHER = "session", "front", "owner", "other"       # what kind_of(name) answers
MOVED, FALLBACK = "moved", "fallback"
GRACE_S = 1800.0           # the audit waits this long after a step is done before it says the next session was not reached


def step_hash(text: Any) -> str:
    """A step's identity for the record: twelve hex digits of its text as the checklist compares it (steps.key)."""
    return hashlib.sha1(_steps.key(text).encode("utf-8")).hexdigest()[:12]


def next_open(meta: dict[str, Any], keeper: str = "") -> tuple[str, str]:
    """(text, opener) of the item's first open step that is not a bare sub-step; ("", "") when there is none."""
    for s in _steps.view(meta, keeper=keeper or str((meta or {}).get("owner") or "")):
        if s["status"] == _steps.OPEN and not _steps.is_bare(s["text"]):
            return s["text"], _steps.opener(s["text"])
    return "", ""


def record_of(meta: dict[str, Any] | None) -> dict[str, Any]:
    r = (meta or {}).get(KEY)
    return r if isinstance(r, dict) else {}


def handled(meta: dict[str, Any] | None, h: str, kind: str) -> bool:
    """Was the step with hash `h` handed over (kind moved) or fallen back on (kind fallback) already?"""
    r = record_of(meta)
    return bool(h) and r.get("step") == h and r.get("kind") == kind


def fresh(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """The record `after` carries when it is new or changed against `before` (another step or another kind), else {}: the History's `step hand-over: …` line, one per hand-over, read from the item diff."""
    a, b = record_of(before), record_of(after)
    return b if b and (a.get("step"), a.get("kind")) != (b.get("step"), b.get("kind")) else {}


def mark(meta: dict[str, Any], h: str, kind: str, to: str, at: float, why: str = "") -> None:
    meta[KEY] = {"step": h, "kind": kind, "to": to, "at": at, **({"why": why[:160]} if why else {})}


def skip_reason(meta: dict[str, Any], mover: str, same: Callable[[str, str], bool], label: Callable[[str], str] = str, owner: str = "the owner") -> str:
    """Why an item is left alone by the hand-over and by the release notice ("" when it is not): on hold, or its needs name a decision or a session other than its mover. One copy for the server and the audit.
    `same(a, b)` says whether two names are one session, `label(name)` shows a name, `owner` is how the owner is called in the words."""
    raw = meta.get("needs")
    needs = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else ([str(raw).strip()] if str(raw or "").strip() else [])
    decision = any(x.lower() == "decision" for x in needs)
    if meta.get("hold") and not decision:
        return "on hold"
    if decision:
        return f"its needs name a decision: it waits on {owner}"
    others = [x for x in needs if x.lower() not in ("decision", "external") and not (mover and same(x, mover))]
    return f"its needs name {', '.join(label(x) for x in others)}, not its mover" if others else ""


def decide(meta: dict[str, Any], keeper: str, mover: str, kind_of: Callable[[str], str], down_of: Callable[[str], str], same: Callable[[str, str], bool]) -> dict[str, Any]:
    """What to do about the first open step after a step was done. `kind_of(name)` says what the opener is (SESSION, FRONT, OWNER, OTHER), `down_of(name)` why a session cannot take the item now ("" when it can),
    `same(a, b)` whether two names are one session. → {"action": "move" | "fallback" | "none", "to": the opener, "step": its text, "hash": its hash, "why": the reason for none and fallback}."""
    text, nm = next_open(meta, keeper)
    out: dict[str, Any] = {"action": "none", "to": nm, "step": text, "hash": step_hash(text) if text else "", "why": ""}
    if not text:
        out["why"] = "no open step is left"
    elif not nm:
        out["why"] = "the next step names no one"
    elif mover and same(nm, mover):
        out["why"] = "the next step is the mover's own"
    else:
        k = kind_of(nm)
        if k == OWNER:
            out["why"] = "the next step is the owner's: no item moves to him by itself"
        elif k == FRONT:
            out["why"] = "the next step is a front agent's: the front-step rule moves it on"
        elif k != SESSION:
            out["why"] = f"{nm} is no session of the fleet"
        elif handled(meta, out["hash"], MOVED):
            out["why"] = "the step was handed over already"
        elif (down := down_of(nm)):
            out.update(action="none" if handled(meta, out["hash"], FALLBACK) else "fallback", why=down if not handled(meta, out["hash"], FALLBACK) else "the mover was told already that this session is down")
        else:
            out["action"] = "move"
    return out
