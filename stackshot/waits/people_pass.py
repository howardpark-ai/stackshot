"""people_pass.py: the data change that stamps the first person on what the store holds without a name (tools/people_migrate.py runs it).

A board that serves one person stores no name on his answers: `people.recorded_by` reads a record with no `by` as the first person, and a decision that names nobody is his by default. The pass writes that
reading down, so the store says who the first person is before a second one is added; it removes no reader, and an item that is left as it is reads the first person all the same (an unapplied or half-applied
store behaves exactly as an applied one).

What a stored item gets (`plan_for`; the server's `one` refuses any item whose reading would change):
  every answer (an entry of metadata.answers, mail ticks included) with no `by`, on an open or a closed item    `by` = the first person's name (people.first), written as the key the readers look at
  an open, alive item that needs a decision, stores no mover and no old picker key, and reads the first person as its mover by default    `mover` = the first person's name
  a line of an open item's `next` that opens with `you:`    the name in its place (the line's writer pair and the stored step that matches it go with it), only when the checklist, the owner reading of every
                       line and the item's state read the same afterwards; otherwise the item keeps the line and is listed with what would differ
A changed item also gets one History line (metadata.stall.log, shown as "stackshot: ..." on an open item; a closed item records it and does not show it); no other key changes, no clock moves, nobody is told, and
nothing is posted to the mirror. When the board names no person (the placeholder "the owner"), nothing is written.

Pure functions of a metadata dict and callbacks: no server import in `plan_for`. `entry_for` builds the undo entry (the keys before and after), `apply_edits` the new item. The log helpers of waits/until_pass.py are the
shared ones."""
from __future__ import annotations

import copy
import re
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import people as _people
from stackshot.model import ids as _ids
from stackshot.model import item_project_pass as _ipp
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.needs import _needs_kinds
from stackshot.waits import mover_pass as _mp
from stackshot.waits import stall as _stall
from stackshot.waits import until_pass as _up

LEGACY = _model.LEGACY_PICKER_KEY
KEYS = ("answers", "mover", "next", "next_by", "steps")        # the keys the pass may change
ENTRY_KEYS = frozenset(KEYS)                                    # what an undo entry's before and after may name
ENTRY_FIELDS = _up.ENTRY_FIELDS                                 # item, before, after, history, dropped
HISTORY_MAX = _up.HISTORY_MAX
_YOU_HEAD = re.compile(r"^[Yy]ou(?=[ \t]*:)")
_YOU_SUB = re.compile(r"(?m)^[Yy]ou(?=[ \t]*:)")
_YOU_LINE = re.compile(r"[Yy]ou[ \t]*:")


def _blank(rec: dict[str, Any]) -> bool:
    return not " ".join(str(rec.get("by") or "").split())


def answers_plan(meta: dict[str, Any], name: str) -> tuple[Any, int]:
    """(the new `answers` list, how many entries got a name) for the answers with no `by`; (None, 0) when there is nothing to stamp. An entry that is not an object, and `answers` that is not a list, are left alone."""
    answers = meta.get("answers")
    if not isinstance(answers, list):
        return None, 0
    out: list[Any] = []
    n = 0
    for rec in answers:
        if isinstance(rec, dict) and _blank(rec):
            rec = {**rec, "by": name}
            n += 1
        out.append(rec)
    return (out, n) if n else (None, 0)


def you_edits(meta: dict[str, Any], name: str) -> tuple[dict[str, Any], list[str]]:
    """The edits that put the first person's name where an open item's `next` opens a line with `you:` ({} when it has none): the text, the writer pair of the line (its key is the hash of the line's text) and the
    stored open step that matches the line (steps match a line by its text). → (edits, rows to list). A `you:` that is not the start of a line of its own (inside a fenced block or a note) leaves the item as it is."""
    text = meta.get("next")
    if not isinstance(text, str) or not text.strip():
        return {}, []
    heads = [c for c in _nl.split(text) if _YOU_LINE.match(c)]
    if not heads:
        return {}, []
    new_text, n = _YOU_SUB.subn(lambda _m: name, text)
    if n != len(heads):
        return {}, ["next has a `you:` at the start of a line that is not a line of its own (inside a fenced block or a note): left as it is"]
    swap: dict[str, str] = {}
    left: dict[str, int] = {}
    for c in heads:
        k = _nl.key_of(c)
        swap[k] = _nl.key_of(_YOU_HEAD.sub(lambda _m: name, c, count=1))
        left[k] = left.get(k, 0) + 1
    edits: dict[str, Any] = {"next": new_text}
    pairs = meta.get("next_by")
    if isinstance(pairs, list):
        new_pairs = copy.deepcopy(pairs)
        for i, p in enumerate(new_pairs):
            if isinstance(p, (list, tuple)) and len(p) == 2 and left.get(str(p[1]), 0) > 0:
                left[str(p[1])] -= 1
                new_pairs[i] = [p[0], swap[str(p[1])]]
        if new_pairs != pairs:
            edits["next_by"] = new_pairs
    steps = meta.get("steps")
    if isinstance(steps, list):
        keys = {_steps.key(c) for c in heads}
        new_steps = copy.deepcopy(steps)
        for s in new_steps:
            if isinstance(s, dict) and s.get("status") == _steps.OPEN and _steps.key(s.get("text")) in keys:
                if not _YOU_HEAD.match(str(s.get("text") or "")):
                    return {}, ["a stored step that matches a `you:` line does not open with `you:` itself: left as it is"]
                s["text"] = _YOU_HEAD.sub(lambda _m: name, str(s["text"]), count=1)
        if new_steps != steps:
            edits["steps"] = new_steps
    return edits, []


def line_probe(meta: dict[str, Any], name: str) -> dict[str, Any]:
    """What the lines of an item's `next` read as, for the check that the `you:` rewrite changes none: the checklist (each step's status, writer, mark, and text with the name where `you:` stood), whether each line is the
    owner's (steps.is_his), the person it opens with, the text without its owner opener, whether it is a bare sub-step, and whose step the first line is (states.next_names_owner)."""
    chunks = _nl.split(meta.get("next"))
    return {
        "checklist": [[s["status"], s.get("writer", ""), s.get("by", ""), s.get("at", 0), _YOU_HEAD.sub(lambda _m: name, _steps.key(s["text"]))] for s in _steps.view(meta)],
        "his": [_steps.is_his(c) for c in chunks],
        "opens": [(_people.opener_person(c).name if _people.opener_person(c) else "") for c in chunks],
        "rest": [_steps.strip_owner(c) for c in chunks],
        "bare": [_steps.is_bare(c) for c in chunks],
        "first": _states.next_names_owner(meta.get("next")),
    }


def probe_diff(a: dict[str, Any], b: dict[str, Any]) -> str:
    """"" when two line probes are equal, else what differs, in words."""
    out = []
    for k in a:
        if a[k] != b[k]:
            if isinstance(a[k], list) and len(a[k]) == len(b[k]):
                at = [i + 1 for i, (x, y) in enumerate(zip(a[k], b[k])) if x != y]
                out.append(f"{k} of line {', '.join(map(str, at))}: {a[k][at[0] - 1]} -> {b[k][at[0] - 1]}")
            else:
                out.append(f"{k} {a[k]} -> {b[k]}")
    return "; ".join(out)


def decision_mover_edit(meta: dict[str, Any], mod: Any, name: str) -> bool:
    """Does an open, alive item that needs a decision store no mover and read the first person as its mover by default (so the pass may store him)? A waiting item, an item with an old picker key, and one whose mover is
    stored (whoever it names) are left as they are."""
    if getattr(mod, "state", "") != _model.ALIVE or "decision" not in _needs_kinds(meta):
        return False
    if LEGACY in meta or _model.clean(meta.get("mover")):
        return False
    return bool(_model.is_owner(mod.mover) and not mod.mover_explicit and _model.clean(mod.mover) == name)


def plan_for(meta: dict[str, Any], mod: Any, is_open: bool) -> dict[str, Any]:
    """The plan for one item → {"edits": {key: new value, None drops}, "form": the changes in words, "listed": True when the item is to be listed, "notes": the rows to list, "answers": how many answers get a name, "why": why nothing is written when the board names no person}.
    `mod`: the model's reading of an open item (None for a closed one, whose answers are the only thing the pass writes). Pure."""
    first = _people.first()
    out: dict[str, Any] = {"edits": {}, "form": "", "listed": False, "notes": [], "answers": 0, "why": ""}
    if first.placeholder:
        out["why"] = "the board names no person: nothing to stamp"
        return out
    name = first.name
    forms: list[str] = []
    edits: dict[str, Any] = {}
    answers, n = answers_plan(meta, name)
    if answers is not None:
        edits["answers"] = answers
        out["answers"] = n
        forms.append(f"by = {name} on {n} answer{'s' if n != 1 else ''}")
    if is_open and mod is not None:
        if decision_mover_edit(meta, mod, name):
            edits["mover"] = name
            forms.append(f"decision's mover stored as {name}")
        you, why = you_edits(meta, name)
        out["notes"] += why
        if you:
            new = {**meta, **you}
            diff = probe_diff(line_probe(meta, name), line_probe(new, name))
            if diff:
                out["notes"].append(f"a `you:` line is kept: with the name in its place the lines would read differently ({diff})")
            else:
                edits.update(you)
                forms.append(f"you: -> {name}: on {len(_nl.split(meta.get('next')))} line(s) of next")
    out["edits"] = {k: v for k, v in edits.items() if meta.get(k) != v}
    out["form"] = "; ".join(forms)
    out["listed"] = bool(out["notes"])
    return out


def history_line(plan: dict[str, Any]) -> str:
    """The History line of a changed item: that the first person was written on what stood with no name, and that nothing else changed."""
    return f"the first person was stamped on what the item stored without a name ({plan['form']}); nothing else on the item changed"[:HISTORY_MAX]


def with_history(meta: dict[str, Any], plan: dict[str, Any], now: float) -> dict[str, Any]:
    """The plan with the History line added (until_pass.with_history, with this pass's line)."""
    if not plan["edits"]:
        return plan
    if not _up._stall_plain(meta):
        return {**plan, "history": "", "dropped": []}
    old = _stall.log_of(meta)
    line = history_line(plan)
    log = (old + [{"at": now, "text": " ".join(line.split())[:240]}])[-_up.LOG_KEEP:]
    stall = dict(meta["stall"]) if isinstance(meta.get("stall"), dict) else {}
    stall["log"] = log
    dropped = [x for x in old if x not in log]
    return {**plan, "edits": {**plan["edits"], "stall": stall}, "history": line, "dropped": dropped}


apply_edits = _up.apply_edits
snapshot = _up.snapshot


def entry_problem(side: Any) -> str:
    """Why an undo entry's side is not one this pass writes ("" = fine): it names only the keys this pass writes."""
    if not isinstance(side, dict) or not side:
        return "an entry side is a non-empty object of the keys the pass changed"
    extra = sorted(k for k in side if k not in ENTRY_KEYS)
    return f"{', '.join(map(str, extra))} is not a key the people pass writes" if extra else ""


def entry_for(item: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """The undo entry for the plan: the keys the plan changes, as they were and as the pass leaves them (never the History log, which later writes add to), the History line it adds and the older lines that pushed
    out. Whole values, so an undo sees a later save that changed one of them and leaves the item alone."""
    keys = [k for k in KEYS if k in plan["edits"]]
    return {"before": snapshot(item, keys), "after": snapshot(apply_edits(item, plan), keys), "history": plan.get("history", ""), "dropped": plan.get("dropped", [])}


def recorded(meta: dict[str, Any]) -> list[str]:
    """Who each stored answer reads as made by (people.recorded_by), for the check that stamping changes no one's authorship."""
    a = meta.get("answers")
    return [_people.recorded_by(r) for r in a] if isinstance(a, list) else []


# ---------------------------------------------------------------------------------------------------------------- the server's side: the ops `people` and `unpeople` of the migration route
# Every function takes `S`, the server module (the running server passes `stamp.PassHost`): the item lock, the file helpers and the refusal shape are the migration route's own. One item at a time under its
# lock, the file read and replaced whole with only the keys above (and the History log) changed (stamp._stamp_write), the file's times kept (a closed item is dated by its file), a sha256 check so a writer
# that takes no lock is never overwritten, and an undo that puts back only what the pass left.
def one(S: Any, gid: str, dry: bool = False) -> dict[str, Any]:
    """Stamp the first person on one item, open or closed → {"item", "status", "action": set | same | kept | moved | refused | would_set, "why", "form", "notes", "answers", "before", "after", "sha256_before"}
    (before and after = the keys the pass changes, None = absent; the stall log is the History line). Worked out HERE, under the item lock, from the file as it stands. `same`: nothing to change; `kept`: nothing
    changed and the item is listed (`notes` says why). `refused`: the item would read differently. `moved`: a writer that takes no lock wrote the item between the read and the replace; its write stands.
    `dry`: nothing is written."""
    shown = S._gh.shown(gid)
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            meta = raw["metadata"]
            is_open = raw.get("status") == "open"
            mod = _mp.prepared(S, gid, raw)[1] if is_open else None
            plan = plan_for(meta, mod, is_open)
            base = {"item": shown, "status": str(raw.get("status") or ""), "form": plan["form"], "notes": plan["notes"], "answers": plan["answers"], "sha256_before": h0}
            if not plan["edits"]:
                return {**base, "action": "kept" if plan["listed"] else "same", "why": "; ".join(plan["notes"]) or plan["why"] or "nothing stored without a name", "before": {}, "after": {}}
            plan = with_history(meta, plan, time.time())
            new = apply_edits(raw, plan)
            out = {**base, **entry_for(raw, plan)}
            why = ""
            if recorded(new["metadata"]) != recorded(meta):
                why = "an answer would read as another person's"
            elif is_open:
                why = _mp.same(_mp.reading(S, gid, raw), _mp.reading(S, gid, new))
            if why:
                return {**out, "action": "refused", "why": f"the item would read differently with the first person stamped: {why}; left as it is"}
            if dry:
                return {**out, "action": "would_set", "why": "the first person would be stamped"}
            if not _ipp.write(S, p, raw, h0, plan["edits"]):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands, and the next run stamps it"}
        return {**out, "action": "set", "why": "the first person stamped"}
    except Exception as e:  # noqa: BLE001  — one item that fails never stops the batch
        print(f"people pass: {gid} not stamped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def undo_one(S: Any, w: Any) -> dict[str, Any]:
    """Put one item's keys back: `w` = {item, before, after, history, dropped} (the keys as they were, and as the pass left them; None = absent). Under the item lock, if the item holds `after` for every key it
    names it gets `before` (None drops the key) → `set`; if it already holds `before` → `same`; anything else (a later save changed a key) → `kept`, untouched. Open or closed. Running it again is a no-op."""
    if not isinstance(w, dict):
        return _mig.refuse("?", "an entry is an object {item, before, after}")
    try:
        gid = _ids._norm_id(str(w.get("item") or ""))
    except ToolError as e:
        return _mig.refuse(str(w.get("item") or "?"), str(e))
    shown = S._gh.shown(gid)
    extra = [k for k in w if k not in ENTRY_FIELDS]
    if extra:
        return _mig.refuse(shown, f"the undo names {', '.join(sorted(map(str, extra)))}: an entry holds item, before, after, history and dropped only")
    history, dropped = w.get("history") or "", w.get("dropped") or []
    if not isinstance(history, str) or not isinstance(dropped, list) or not all(isinstance(x, dict) for x in dropped):
        return _mig.refuse(shown, "history is the line the pass added (text) and dropped a list of log lines")
    before, after = w.get("before"), w.get("after")
    for side in (before, after):
        why = entry_problem(side)
        if why:
            return _mig.refuse(shown, why)
    if set(before) != set(after):
        return _mig.refuse(shown, "before and after name the same keys")
    keys = list(before)
    try:
        with S._writes.ITEM_LOCK:
            p, data, raw, refusal = S._stamp_open(gid, shown, closed_ok=True)
            if refusal is not None:
                return refusal
            h0 = S._stamp_sha(data)
            now = snapshot(raw, keys)
            out = {"item": shown, "before": before, "after": after, "history": history, "dropped": dropped, "sha256_before": h0}
            if now == before:
                return {**out, "action": "same", "why": "it already holds the keys it had"}
            if now != after:
                return {**out, "action": "kept", "why": "it holds other values than the pass left (a later save changed them): left as it is", "now": now}
            edits = {k: before[k] for k in keys if before[k] != after[k]}
            if history:
                edits["stall"] = _up._log_without(raw["metadata"], history, dropped)
            if not _ipp.write(S, p, raw, h0, edits):
                return {**out, "action": "moved", "why": "the item was written between the read and the replace: its write stands"}
        return {**out, "action": "set", "why": "the keys put back"}
    except Exception as e:  # noqa: BLE001
        print(f"people pass: {gid} not put back: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _mig.refuse(shown, f"{e.__class__.__name__}: {str(e)[:200]}")


def write_op(S: Any, spec: dict[str, Any], op: str, by: str) -> dict[str, Any]:
    """op people {items: [id, …], pass_id?, dry?} | unpeople {items: [{item, before, after, history, dropped}, …], pass_id?} (at most _mig.BATCH): the people pass over every item, open or closed. No begin and no
    hold: each item is worked out and written under its own lock (`one`). `dry` (people only) writes nothing and answers what each item would get. One publish at the end when anything was written.
    → {"op", "results": [...]}."""
    extra = [k for k in spec if k not in S._STAMP_BODY]
    if extra:
        raise ToolError(f"Refused: {op} takes op, sender, items, pass_id and dry only (got {', '.join(sorted(map(str, extra)))}): it writes the first person on what is stored without a name and nothing else")
    items = spec.get("items")
    if not isinstance(items, list) or not items or len(items) > _mig.BATCH:
        raise ToolError(f"Refused: items is a list of 1 to {_mig.BATCH} " + ("item ids" if op == "people" else "entries {item, before, after}"))
    pid = str(spec.get("pass_id") or "")
    if pid and not _mig.PASS_ID_RX.fullmatch(pid):
        raise ToolError("Refused: pass_id is <YYYYMMDD-HHMMSS>-<6 hex>")
    dry = bool(spec.get("dry"))
    if dry and op != "people":
        raise ToolError("Refused: dry goes with people only")
    results: list[dict[str, Any]] = []
    for it in items:
        if op == "unpeople":
            results.append(undo_one(S, it))
            continue
        try:
            gid = _ids._norm_id(str(it or ""))
        except ToolError as e:
            results.append(_mig.refuse(str(it or "?"), str(e)))
            continue
        results.append(one(S, gid, dry=dry))
    if any(r["action"] == "set" for r in results):
        S._pubmod._publish()
    if pid and not dry:
        S._stamp_pass_keep(pid, by, op, results)
    return {"op": op, "results": results}
