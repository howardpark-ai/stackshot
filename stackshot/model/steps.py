"""steps.py — the checklist behind `next` (it retains all actions already taken or to be taken on the item, as a checkbox list, taken ones checked and slightly dimmed;
open items start the list now; a dropped step stays, struck through).

THE STORAGE (the one decision of this module). `metadata.next` stays what it always was: the text of the OPEN lines, one step per top-level line. Every reader of next (the brief, the notices, the home
rows, the GitHub mirror, `get`, the write guards, the router, search) reads that text and is untouched. Beside it `metadata.steps` is the checklist: a list, in the order the steps were written, of

    {"text": <the step as written, its sub-lines included>, "status": "open" | "done" | "dropped", "by": <who marked it>, "at": <epoch seconds it was marked>,
     "tag": {"text": <a few words>, "state": <in progress | done | …>, "ts": <epoch seconds>}}

`tag` is the step's status line (optional): where the step's session is with it ("PR 83 up", "review, scan running"). A `work` write of the update tool changes the tag of the sender's first open step in
place, so a step that takes a night keeps one line, not one line per status; it follows the step's text (the key) through a reorder and stays on the step when it is marked.

(The item page draws the finished steps first, then the open ones: `drawn_order`; the stored order is unchanged.) `next` is derived from it: the open steps' text joined by newlines (an update that writes `next` keeps the text exactly as written, and the steps follow it). A step is a line of next as
nextlines.split groups it (the one rule for what a line is), and the writer of each open line is the one nextlines keeps in `metadata.next_by`, so a step is the sender's own or another
session's. A write path that knows nothing
of steps (a test, the migration, an old client) only changes `next`: `view` lines the stored steps up with the text it finds, so a step whose line is gone reads as dropped and a line that
is new reads as an open step at the end. An item with no `steps` yet has the checklist its `next` lines give (all open): the list starts from now, no backfill from History.

Pure functions of an item's metadata and strings: no server import (it reads nextlines and model_guards for the one copy of what a line of next is), so the server, the renderer and the tests share them."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import nextlines as _nl

OPEN, DONE, DROPPED = "open", "done", "dropped"
STATUSES = (OPEN, DONE, DROPPED)
_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def key(text: Any) -> str:
    """A step as compared: its text on one line, the list marker of its first line and the bold marks left out."""
    return _nl.norm(text)


def first_line(text: Any) -> str:
    """The step's first line (marker and bold marks off), what a History line and a refusal quote."""
    for ln in str(text or "").splitlines():
        if ln.strip():
            return key(ln)
    return ""


def split(text: Any) -> list[str]:
    """The steps of a next text, each as written: nextlines.split, the one rule for what a line of next is (a top-level line with the indented lines, notes and fenced blocks under it)."""
    return _nl.split(text)


def join(texts: list[str]) -> str:
    return "\n".join(texts)


TAG = "tag"
TAG_STATES = ("defined", "assigned", "in progress", "done")


def tag_of(step: dict[str, Any] | None) -> dict[str, Any] | None:
    """The step's status tag as {text, state, ts}, None when it has none or a misshaped one."""
    t = (step or {}).get(TAG)
    if not isinstance(t, dict):
        return None
    text = clean(t.get("text"))
    if not text:
        return None
    st = clean(t.get("state")).lower()
    try:
        ts = float(t.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    return {"text": text, "state": st if st in TAG_STATES else "in progress", "ts": ts}


def _with_tag(step: dict[str, Any], tag: dict[str, Any] | None) -> dict[str, Any]:
    if tag:
        step[TAG] = dict(tag)
    return step


def _valid(v: Any) -> list[dict[str, Any]]:
    out = []
    for s in v if isinstance(v, list) else []:
        if isinstance(s, dict) and str(s.get("text") or "").strip() and s.get("status") in STATUSES:
            out.append(_with_tag({"text": str(s["text"]), "status": s["status"], "by": clean(s.get("by")), "at": s.get("at") or 0}, tag_of(s)))
    return out


def _step(text: str, status: str = OPEN, by: str = "", at: float = 0) -> dict[str, Any]:
    return {"text": text, "status": status, "by": by, "at": at}


def view(meta: dict[str, Any] | None, closed: bool = False, keeper: str = "") -> list[dict[str, Any]]:
    """The checklist of an item as its metadata gives it, in the order the steps were written: the stored steps with their open ones lined up with the lines of `next` (a stored open
    step whose line is no longer in next reads as dropped, with nobody and no time; a line of next that matches no stored step is a new open step at the end). A closed item's
    steps are the record as stored (its next is gone; a close marks the open ones, so a closed item shows none open, except an old one the backfill has not reached). Each step is a new dict; an open one also carries `writer`, the session whose
    write put its line in next (nextlines; `keeper`, default the item's creator, for a line with none stored)."""
    m = meta or {}
    stored = _valid(m.get("steps"))
    if closed:
        return stored
    rows = _nl.resolve(m, keeper or str(m.get("owner") or ""))
    chunks = [e for e, _ in rows]
    writers = [w for _, w in rows]
    keys = [key(c) for c in chunks]
    used: set[int] = set()
    out: list[dict[str, Any]] = []
    for s in stored:
        if s["status"] != OPEN:
            out.append(s)
            continue
        k = key(s["text"])
        j = next((j for j, kk in enumerate(keys) if j not in used and kk == k), -1)
        if j >= 0:
            used.add(j)
            out.append(_with_tag({**_step(chunks[j]), "writer": writers[j]}, tag_of(s)))
        else:
            out.append(_with_tag(_step(s["text"], DROPPED), tag_of(s)))
    out += [{**_step(c), "writer": writers[j]} for j, c in enumerate(chunks) if j not in used]
    return out


def drawn_order(steps: list[dict[str, Any]], extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The checklist in the order the item page draws it: the finished steps first, done and dropped together in the order they were marked
    (by `at`, earliest first; a step with none counts as time 0; ties keep their stored order), then the open steps in their stored (planned) order. `extra` is rows that are not steps but are
    drawn among the finished ones by their `at` (the page's rows for his decisions: they follow the steps on a tie). Drawing only: the stored steps, `next`, the tools' text and the positions
    `done=[…]` / `dropped=[…]` take are all in the order `view` gives, and stay so."""
    fin = [s for s in steps if s["status"] != OPEN] + list(extra or [])
    return sorted(fin, key=lambda s: float(s.get("at") or 0)) + [s for s in steps if s["status"] == OPEN]


def open_text(steps: list[dict[str, Any]]) -> str:
    """The `next` text of a checklist: its open steps, in order."""
    return join([s["text"] for s in steps if s["status"] == OPEN])


def close_status(outcome: Any) -> str:
    """The mark a close puts on the steps still open: done when the item closed `done`, dropped for every other outcome (dropped, superseded, or none recorded)."""
    return DONE if str(outcome or "").strip().lower() == "done" else DROPPED


def mark_open(steps: list[dict[str, Any]], outcome: Any, by: str, at: float) -> list[dict[str, Any]]:
    """The checklist with every step still open marked by the closer: done when the outcome is done, dropped otherwise, `by` and `at` like any other mark. Marked steps stay as they are."""
    st = close_status(outcome)
    return [_with_tag(_step(s["text"], st, by, at), _done_tag(tag_of(s), st)) if s["status"] == OPEN else dict(s) for s in steps]


def _done_tag(tag: dict[str, Any] | None, status: str) -> dict[str, Any] | None:
    """The tag of a step as it is marked: a step marked done reads done on its status line too (the text stays); a dropped step keeps its tag as it was."""
    return {**tag, "state": "done"} if tag and status == DONE else tag


def close_meta(meta: dict[str, Any], outcome: Any, by: str, at: float, keeper: str = "") -> None:
    """A close that goes through no `update` (the server's own: a done check, a watcher's drop) marks the item's open steps in its metadata, before the close clears next. An item with no steps writes none."""
    cl = view(meta, keeper=keeper)
    if cl:
        meta["steps"] = stored(mark_open(cl, outcome, by, at))


def counts(steps: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(open, done, dropped)."""
    return tuple(sum(1 for s in steps if s["status"] == st) for st in STATUSES)      # type: ignore[return-value]


def stored(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The steps as they are stored: text and status, and for a marked step the marker's name and time (the writer of an open line is nextlines' record, not stored here)."""
    out = []
    for s in steps:
        e: dict[str, Any] = {"text": s["text"], "status": s["status"]}
        if s["status"] != OPEN:
            e["by"] = s.get("by") or ""
            e["at"] = s.get("at") or 0
        out.append(_with_tag(e, tag_of(s)))
    return out


class StepError(ValueError):
    """A write the checklist refuses; the message says what to pass instead."""


def numbered(steps: list[dict[str, Any]], only: str = "") -> str:
    """The steps one per line with their positions (`2. text`), the first line of each; `only` limits them to one status."""
    return "; ".join(f"{i}. {first_line(s['text'])[:90]}" for i, s in enumerate(steps, 1) if not only or s["status"] == only)


def resolve(steps: list[dict[str, Any]], refs: Any, param: str, verb: str = "marked") -> list[int]:
    """The 0-based indexes the refs of `done`, `dropped` or `reword` (the keys of its mapping; `verb` is then "reworded") name. A ref is a 1-based position in the checklist (a number, or text of digits) or the exact text of an open step's first line
    (or the whole step, as written, marker and bold marks aside). Refused (StepError): an unknown position, a step that is no longer open, text that matches no open step or more than one."""
    if refs is None:
        return []
    if isinstance(refs, str) and refs.strip().startswith("["):         # a client that sends the list as a JSON string
        try:
            refs = json.loads(refs)
        except ValueError:
            pass
    if isinstance(refs, (list, tuple)):
        items = list(refs)
    elif isinstance(refs, str) and re.fullmatch(r"\s*\d+(?:\s*,\s*\d+)*\s*", refs):
        items = [x for x in re.split(r"\s*,\s*", refs.strip()) if x]
    else:
        items = [refs]
    out: list[int] = []
    for ref in items:
        if isinstance(ref, bool):
            raise StepError(f"{param} takes step positions (1 to {len(steps)}) or the exact text of an open step")
        if isinstance(ref, int) or (isinstance(ref, str) and re.fullmatch(r"\s*\d+\s*", ref)):
            n = int(ref)
            if not 1 <= n <= len(steps):
                raise StepError(f"{param}: there is no step {n}; the checklist has {len(steps)}" + (f" ({numbered(steps)})" if steps else " (it is empty)"))
            i = n - 1
        else:
            k = key(ref)
            if not k:
                raise StepError(f"{param} holds an empty entry; pass a step's position or its exact text")
            hits = [j for j, s in enumerate(steps) if s["status"] == OPEN and (key(s["text"]) == k or first_line(s["text"]) == k)]
            if not hits:        # the owner's name left off, put on, or stored twice: the words are the same step (an owner-led step only; any other step is found by its whole text)
                lk = loose_key(ref)
                hits = [j for j, s in enumerate(steps) if s["status"] == OPEN and (loose_key(s["text"]) == lk or loose_key(first_line(s["text"])) == lk)]
            if not hits:
                raise StepError(f"{param}: no open step reads {clean(ref)[:90]!r}; the open steps are " + (numbered(steps, OPEN) or "none"))
            if len(hits) > 1:
                raise StepError(f"{param}: {clean(ref)[:90]!r} matches steps {', '.join(str(j + 1) for j in hits)}; pass the position")
            i = hits[0]
        if steps[i]["status"] != OPEN:
            raise StepError(f"{param}: step {i + 1} is already {steps[i]['status']} ({first_line(steps[i]['text'])[:90]}); only an open step is {verb}")
        if i not in out:
            out.append(i)
    return out


def reword_given(spec: Any) -> bool:
    """Does a `reword` argument name a step? Not None, not an empty mapping ({} or the string "{}"), not blank text. Anything else is given, a string that is no mapping included (resolve_reword refuses it)."""
    if spec is None:
        return False
    if isinstance(spec, str):
        if not spec.strip():
            return False
        try:
            spec = json.loads(spec)
        except ValueError:
            return True
    return not (isinstance(spec, dict) and not spec)


def resolve_reword(steps: list[dict[str, Any]], spec: Any) -> dict[int, str]:
    """The `reword` parameter of update: a mapping from an open step to its new text, as {0-based index: the new text, as written} for the steps whose words change. A key is read as `done` and
    `dropped` read a ref: a 1-based position in the checklist (a number, or text of digits, which is what a JSON key is) or the exact text of an open step's first line. A JSON string of the
    mapping is read too. A new text that already reads as the step is left out (nothing to change). Refused (StepError): not a mapping, an empty text, a text of more than one step, a position
    that is not there or a step that is not open (the same texts as `done`), the same step twice, and a new text that reads as another open step (a duplicate)."""
    if spec is None:
        return {}
    if isinstance(spec, str):
        if not spec.strip():
            return {}
        try:
            spec = json.loads(spec)
        except ValueError:
            raise StepError('reword takes a mapping from a step\'s position to its new text, e.g. reword={3: "my-x: new words"}')
    if not isinstance(spec, dict):
        raise StepError('reword takes a mapping from a step\'s position to its new text, e.g. reword={3: "my-x: new words"}')
    out: dict[int, str] = {}
    for ref, text in spec.items():
        (i,) = resolve(steps, [ref], "reword", "reworded")
        if not isinstance(text, str) or not text.strip():
            raise StepError(f"reword: the new text of step {i + 1} must be a non-empty string")
        if len(split(text)) != 1:
            raise StepError(f"reword: the new text of step {i + 1} is more than one step; a reword changes one step's words, and a further step is a line of next")
        if i in out:
            raise StepError(f"reword: step {i + 1} is named twice")
        if key(text) != key(steps[i]["text"]):
            out[i] = text.strip()
    for i, text in out.items():
        for j, text_j in out.items():
            if j > i and key(text) == key(text_j):
                raise StepError(f"reword: steps {i + 1} and {j + 1} would both read {first_line(text)[:90]!r}; two open steps never read the same, so mark one of them instead")
        for j, s in enumerate(steps):          # against the text every open step holds now, a reworded one's old text included: a swap or a shift of texts ({1: B, 2: A}) is never one call
            if j != i and s["status"] == OPEN and key(s["text"]) == key(text):
                raise StepError(f"reword: step {i + 1} would read the same as open step {j + 1} ({first_line(s['text'])[:90]})" + (
                    ", whose own words change in this call too; a swap or a shift of texts between steps is not one reword, so reword them in separate calls with a different text between" if j in out else "; mark one of them instead"))
    return out


def retry_call(positions: list[int]) -> str:
    """The calls that settle the steps at `positions` (1-based) a write left out of next, in one short line: done, dropped or reword, with the numbers filled in."""
    pos = ",".join(str(p) for p in positions)
    words = ", ".join(str(p) + ': "<new text>"' for p in positions)
    return f"done=[{pos}], dropped=[{pos}] or reword={{{words}}}"


def apply(old: list[dict[str, Any]], new_next: str | None, done: list[int], dropped: list[int], by: str, at: float, *, written: str = "",
          own: Callable[[str], bool] | None = None, wipe: bool = False, strict: bool = True, reworded: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """The checklist after a write: `old` is view() of the item before it, `new_next` the item's next text as the write leaves it (None when the call leaves next alone), `done` and `dropped` the indexes
    it marks (any open step, whoever wrote it), `written` the next text the call itself wrote (its own lines, for the check below). The marked steps change in place and keep their position.
    With a new next, the open steps are lined up with its lines (any order, new steps allowed). A step whose line is no longer there and that the call did not mark is
      * dropped, by `by` now, when `wipe` (clear_next=true is a deliberate wipe);
      * refused (StepError) with the parameters to pass when it is the sender's own (`own(writer)`; nextlines replaces only the sender's lines, so another session's line never leaves this way)
        (`strict` False: [metadata.next] require_marks = false, the way back: it reads as dropped, with nobody and no time, as view() reads a line that left next);
      * dropped with nobody for any other line (a write that knows nothing of steps took it out).
    The open steps take the order of next's lines, in the places the open steps held, and new ones go at the end. A step this call marks that its own `written` text lists again is refused: next holds the open steps only.
    Without a next, what is open stays. `reworded` is the steps this call rewords (`old` already holds their new text): one of them that next does not list is refused with its own text, since next lists the lines as they read after the reword."""
    both = set(done) & set(dropped)
    if both:
        i = min(both)
        raise StepError(f"step {i + 1} is in both done and dropped ({first_line(old[i]['text'])[:90]}); pick one")
    steps = [dict(s) for s in old]
    for idx, st in ((done, DONE), (dropped, DROPPED)):
        for i in idx:
            steps[i] = _with_tag(_step(steps[i]["text"], st, by, at), _done_tag(tag_of(steps[i]), st))
    marked = {key(old[i]["text"]) for i in (*done, *dropped)}
    left = {k: sum(1 for s in steps if s["status"] == OPEN and key(s["text"]) == k) for k in marked}      # the open steps still reading k once this call's marks are in
    listed: dict[str, int] = {}
    clash = []
    for c in split(written):
        k = key(c)
        if k in marked:
            listed[k] = listed.get(k, 0) + 1
            if listed[k] > left[k]:           # a copy of the same text that stays open (a duplicate step) may stay in next; the marked step's own line may not
                clash.append(first_line(c))
    if clash:
        raise StepError(f"next still lists {clash[0][:90]!r}, which this call marks done or dropped; next holds the open steps only: take the line out of next")
    if new_next is None:
        return steps
    chunks = split(new_next)
    keys = [key(c) for c in chunks]
    open_idx = [i for i, s in enumerate(steps) if s["status"] == OPEN]
    used: dict[int, int] = {}
    for i in open_idx:
        k = key(steps[i]["text"])
        j = next((j for j, kk in enumerate(keys) if j not in used.values() and kk == k), -1)
        if j >= 0:
            used[i] = j
    gone = [i for i in open_idx if i not in used]
    if gone and wipe:
        for i in gone:
            steps[i] = _with_tag(_step(steps[i]["text"], DROPPED, by, at), tag_of(steps[i]))
    else:
        said_rw = [i for i in gone if reworded and i in reworded]
        if said_rw:
            i = said_rw[0]
            raise StepError(f"reword gives step {i + 1} the text \"{first_line(steps[i]['text'])[:90]}\", and the next in this call does not list that text: next lists the lines as they read after the reword. "
                            "Write the new text in next, or leave next out of the call and the line is changed for you")
        mine = [i for i in gone if own is None or own(str(steps[i].get("writer") or ""))]
        if mine and strict:
            lost = "; ".join(f"{i + 1}. {first_line(steps[i]['text'])[:90]}" for i in mine)
            one = len(mine) == 1
            raise StepError(f"next no longer lists {len(mine)} of your open step{'' if one else 's'} and the call does not say what became of {'it' if one else 'them'}: {lost}.\n"
                            f"Retry with {retry_call([i + 1 for i in mine])}.\n"
                            f"Mark {'it' if one else 'each'} in the same update, done if the work was done or dropped if it is no longer wanted (positions in the checklist or exact line text), reword {'it' if one else 'each'} to change its words, or keep the line in next; "
                            "a reworded line counts as a new step, so reword the step itself (reword), or mark the old one (dropped=[n]) and write the new text; clear_next=true wipes every line and marks them dropped. "
                            "If this tool shows no done/dropped/reword parameter, call stackshot_update through the MCP Portal's Code Mode (portal_codemode_execute with codemode.stackshot_update({…, done:[…]})), or use clear_next=true")
        for i in gone:
            steps[i] = _with_tag(_step(steps[i]["text"], DROPPED), tag_of(steps[i]))
    open_idx = [i for i in open_idx if i in used]
    order = sorted(used.values())
    tags = {key(s["text"]): tag_of(s) for s in old if s["status"] == OPEN and tag_of(s)}      # a status line follows its step's words through a reorder
    for slot, j in zip(open_idx, order):
        steps[slot] = _with_tag(_step(chunks[j]), tags.get(keys[j]))
    taken = set(used.values())
    steps += [_step(c) for j, c in enumerate(chunks) if j not in taken]
    return steps


def changes(before: dict[str, Any] | None, after: dict[str, Any] | None, closed: bool = False) -> list[tuple[str, str]]:
    """[(done | dropped, the step's first line)] for the steps a write marked, between the metadata before it and after it, in checklist order: the History's `step done: …` and
    `step dropped: …` lines. A step that left next with nobody marking it (a write that knows nothing of steps) is no event here: the line of next says it. `closed`: `after` is a closed item's; the mark a close puts on its open steps by itself (done for outcome done, dropped otherwise) is no event here, the close line says it, so only
    a step marked the other way in the same call is listed."""
    pv, nv = view(before), view(after, closed=closed)
    by_close = close_status((after or {}).get("outcome")) if closed else ""
    out = []
    for i, x in enumerate(nv):
        if i < len(pv) and pv[i]["status"] == OPEN and x["status"] in (DONE, DROPPED) and x["status"] != by_close and x.get("at") and key(pv[i]["text"]) == key(x["text"]):
            out.append((x["status"], first_line(x["text"])))
    return out


# ---------------------------------------------------------------------------------------------------------------- whose step it is
def opener(text: Any) -> str:
    """The name before the colon that opens a step's first line (`the owner`, `my-x`), "" when it opens with none."""
    first = next((ln for ln in str(text or "").splitlines() if ln.strip()), "")
    m = _mg._NAME_RX.match(_mg._MARK_RX.sub("", first.strip().replace("**", "")))
    return m.group("name") if m else ""


def is_his(text: Any, unnamed_is_his: bool = True) -> bool:
    """Is the step the owner's: it opens with his name (`<owner>:`, or the instance's owner name, `the owner:`), or with none (`unnamed_is_his`, true unless a caller passes false: a line that names nobody counts as his)?"""
    nm = opener(text)
    return _model.is_owner(nm) if nm else unnamed_is_his


def strip_opener(line: Any) -> str:
    """A step's first line without its list marker and its `<name>: ` opener (a line whose opener is wrapped in bold keeps its bold marks off): the action alone."""
    t = _MARKER.sub("", str(line or "").strip(), count=1)          # a bullet needs a space after it: "**<owner>:**" opens with bold, not a bullet
    if not _mg._NAME_RX.match(t.replace("**", "")):
        return t
    return re.sub(r"^\*{0,2}[^:*]{1,40}:\*{0,2}[ \t]*", "", t, count=1).strip()


def _owner_led(text: Any) -> bool:
    nm = opener(text)
    return bool(nm) and _model.is_owner(nm)


def strip_owner(line: Any) -> str:
    """A line without its opener and without any further owner opener that follows it (`Name: Name: x` and `Name (role): name: x` both give `x`); an opener that is not the owner's stays after the first."""
    t = strip_opener(line)
    for _ in range(8):
        if not _owner_led(t):
            break
        s = strip_opener(t)
        if s == t:
            break
        t = s
    return t


def without_owner(text: Any) -> str:
    """A step's text on one line without the owner's name at its front, however many times and in whatever spelling the opener stands there (any case, a role in parentheses, a list marker or bold marks around it);
    a text that does not open with the owner's name comes back as it is, on one line."""
    t = clean(text)
    return strip_owner(t) if _owner_led(t) else t


def collapse_owner(line: Any) -> str:
    """A line as it is shown: an owner opener repeated at its front (a step stored with his name twice, before the server stopped doubling it) reads with it once; any other line comes back as it is."""
    t = str(line or "")
    if _owner_led(t) and _owner_led(strip_opener(t)):
        return f"{_model.owner_display()}: {strip_owner(t)}"
    return t


def owner_key(text: Any) -> str:
    """A step as compared when it may be the owner's: `key`, with the owner's opener written one way (`<owner>: `) and only once, so `Name: x`, `Name: Name: x`, `name (role): x` and a bulleted or bold form
    are one step, and a step stored with the name twice still matches the one-name form."""
    k = key(text)
    return f"{_model.owner_display()}: {strip_owner(k)}" if _owner_led(k) else k


def loose_key(text: Any) -> str:
    """The step's words for a reference that may leave the owner's name off: `key`, and for an owner-led step the text after all of its owner openers."""
    k = key(text)
    return strip_owner(k) if _owner_led(k) else k


def is_bare(text: Any) -> bool:
    """Is the step a bullet or a numbered line that names no one (`- a sub step`)? nextlines counts it a line of its own (a step, checkable and markable), but it reads as a sub-step of the line above,
    so the page draws it without the item's mover put in front of it."""
    first = next((ln for ln in str(text or "").splitlines() if ln.strip()), "")
    return bool(_MARKER.match(first)) and not opener(first)
