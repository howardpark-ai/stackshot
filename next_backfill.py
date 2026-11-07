"""next_backfill.py — the one-off fill-in of the owner's past decisions as done steps (the Next design, "Past decisions on open items are filled in from the saved answers. Closed items are left as they are").

Before the server made his steps (part 1), his answer to a decision left no step behind: the answer is saved on the item (`metadata.answers`, each with its exact time), the checklist shows nothing. This module works out,
for ONE item, the done steps his saved decisions would have left, exactly as `server._answer` leaves them now (owner_steps.tick): `<owner>: <what he was asked> → <what he picked>`, done by him at the answer's time.

  - Only an OPEN item. A closed item is the record as it is.
  - Only the `decision` answers. A comment is no decision; a note on a step (`step-reply`) leaves its step open for the session that judges it.
  - What he was asked is the Decide part of the ask saved with the answer; a Done on a step shows that step; an answer saved with neither reads `answer the ask on the item` (the words the server uses for an ask-less item).
  - An answer already on the checklist is not added again: a done step of his within 5 seconds of the answer's time, or a done step of his that says the same question (an agent ticked it before part 1; N4 is left to the audit,
    nothing is rewritten). So the fill-in is idempotent: a second run adds nothing.
  - The steps are appended after the checklist as it reads now (view), in the order he answered: no existing position moves, and the item page draws finished steps by their time anyway.

Pure functions on an item's metadata dict, no server import and no store access: the server writes (server._migrate_one, the `backfill` write), recomputing from the item's own saved answers."""
from __future__ import annotations

from typing import Any

import owner_steps as _hs
import model as _model
import steps as _steps

NEAR = 5.0                      # seconds: a done step of his this close to an answer's time is that answer's step
NONE_TEXT = "answer the ask on the item"      # server._OWNER_STEP_NONE, the step of an item that asked with no ask line


def _base(rec: dict[str, Any]) -> str:
    """The question his answer was to, as his step reads (the text after `<owner>: `)."""
    step = _steps.clean(rec.get("step"))
    if step:
        return step
    return _hs.decide_of(rec.get("ask")) or NONE_TEXT


def _stem(text: Any) -> str:
    """A step's first line without its `→ answer`, as compared."""
    ln = _steps.first_line(text)
    return _steps.owner_key(ln.split(_hs.ARROW.strip(), 1)[0]) if _hs.ARROW.strip() in ln else _steps.owner_key(ln)


def plan(meta: dict[str, Any] | None, status: str = "open", keeper: str = "") -> list[dict[str, Any]]:
    """The steps to add for one item: [{"ts", "line" (the whole step), "base", "answer"}] in the order he answered; [] for a closed item or nothing missing. `skipped` rows are in `audit`."""
    return audit(meta, status, keeper)[0]


def audit(meta: dict[str, Any] | None, status: str = "open", keeper: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rows to add, rows already on the checklist): the second list holds {"ts", "line", "why"} for each saved decision that needs no step (`why`: `step there` or `ticked by <who>`)."""
    m = meta or {}
    if status != "open":
        return [], []
    cl = _steps.view(m, keeper=keeper or str(m.get("owner") or ""))
    his = [s for s in cl if s["status"] == _steps.DONE and _hs.is_named(s["text"])]
    add: list[dict[str, Any]] = []
    have: list[dict[str, Any]] = []
    recs = [r for r in (m.get("answers") if isinstance(m.get("answers"), list) else []) if isinstance(r, dict) and r.get("kind") == "decision"]
    for rec in sorted(recs, key=lambda r: float(r.get("ts") or 0)):
        try:
            ts = float(rec.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        base = _base(rec)
        ans = _hs.answer_words(rec.get("choice"), rec.get("text"))
        line = _hs.with_answer(_hs.line_of(base), ans)
        near = next((s for s in his if abs(float(s.get("at") or 0) - ts) <= NEAR), None)
        same = next((s for s in his if _stem(s["text"]) == _steps.owner_key(_hs.line_of(base))), None)
        if near is not None:
            have.append({"ts": ts, "line": line, "why": "step there"})
        elif same is not None:
            have.append({"ts": ts, "line": line, "why": f"ticked by {same.get('by') or 'someone'}"})
        else:
            add.append({"ts": ts, "line": line, "base": base, "answer": ans})
    return add, have


def apply(meta: dict[str, Any], rows: list[dict[str, Any]], keeper: str = "") -> int:
    """Append the done steps of `rows` (plan's) to the item's checklist in `meta`, done by him at each answer's time → how many. Nothing else in the metadata changes (next, the open steps and the writers stay)."""
    if not rows:
        return 0
    cl = _steps.view(meta, keeper=keeper or str(meta.get("owner") or ""))
    who = _model.owner_display()
    for r in rows:
        cl.append({"text": r["line"], "status": _steps.DONE, "by": who, "at": r["ts"]})
    meta["steps"] = _steps.stored(cl)
    return len(rows)
