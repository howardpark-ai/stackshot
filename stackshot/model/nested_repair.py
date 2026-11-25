"""nested_repair.py: the open items whose long step was split into flat lines before a list under a lead-in was split into one line with sub-lines, read in the new shape.

A long step once split into one flat line of next per action, a lead-in that ends with a colon and each item of its numbered list included (step_split.py). Now such a list is one line with the items
as indented `- ` lines under it, and the checklist ticks it as one step. This puts an item that was split the old way into the new shape, once, and says what it did.

WHAT IT TOUCHES. Only an open item that records the lines the server made from its step (metadata.step_lines, kept while the step is stored): a line the server made is a split's line by its record, and a line
that a writer wrote flat on purpose has none, so it is never read as a list. Within the open lines of next that are in that record, a run of three or more, one after the other, single-line, his, written by one session. In
a run the first line whose words end with a colon and that has at least two lines after it is the lead-in; the lines after it become its items (each on a `- ` line under it, his name off), and the lines before
it stay as they are. THE ONE GUESS: the old split dropped the numbers and the full stops, so the last item and a closing sentence after it read the same. The last line is taken for a closing sentence (and left
a line of its own) only when there are at least three lines after the lead-in, it starts with a capital letter and no line before it does; in every other run every line after the lead-in is an item.

THE WORDS ARE KEPT. An item's text is the line as it stands, with only its list marker and his name's opener taken off: no `**` removed, no spaces collapsed (`git add **/*.md`, `2**8`, a command with two spaces, a bold
word all come out byte for byte). The normalised key (steps.key) is for matching lines only, never for what is written.

POSITIONS, NOT WORDS. The lines that are nested, and the checklist steps of them, are found by their place among the lines of next (nextlines.resolve, steps.view_rows), so an earlier open line that reads the same
as an item is never the one taken out.

THE SUMMARY. The summary the old split stored ends `(+N more)`, N the lines after the first; with the items nested N is smaller by their number. When the server's own line for the summary (metadata.owner_step) is the
line of that step, summary and line are reworded together in place (the position, the writer and the tick of the line kept), so the next save finds them agreeing and drops and adds nothing. A summary with no such tail, a line
of the server's that does not match it, or one a proof waits on, is left as it is.

TICKS. A line already ticked done or dropped is no open line, so it is in no run: it stays on the checklist as it was, and the open lines around it are nested as they stand. The merged line is the lead-in's step (its tag, its
writer, its place in next kept), the lines nested into it leave the checklist (they are in the lead-in's step now) and `step_lines` follows. A run holding a line that a proof (metadata.step_proof) waits on, or the line the
server keeps for the step itself (metadata.owner_step), is left as it is.

IDEMPOTENT: the merged line has sub-lines, so it is no single-line line and starts no run; a second pass finds nothing and changes nothing.

Pure functions on an item's metadata dict (`nest` changes it in place; the dry run is `plan`, which does not): no store, no server."""
from __future__ import annotations

import re
from typing import Any, NamedTuple

from stackshot.model import nextlines as _nl
from stackshot.model import owner_steps as _os
from stackshot.model import step_split as _ss
from stackshot.model import steps as _steps

RUN_MIN = 3                  # a lead-in and at least two lines after it
FIELDS = ("next", "next_by", "steps", "step_lines", "step", "owner_step")      # what the repair can change on the metadata: an undo record keeps these as they were
_TAIL = re.compile(r"^(?P<head>.*?) \(\+(?P<n>\d+) more\)$", re.S)


class Plan(NamedTuple):
    at: int                  # the lead-in's position among the lines of next
    n: int                   # how many lines right after it become its items
    lead: str
    items: list[str]
    left: list[str]          # the other lines of the run, which stay


def _body(entry: str) -> str:
    """The action of a line of his, as written: the line without its list marker and his name's opener, nothing else (no bold marks removed, no spaces collapsed: steps.key is for matching, not for text).
    A line of a run is one line."""
    return _steps.strip_owner(entry.strip()).strip()


def _closing_split(after: list[str]) -> int:
    """How many of the lines after the lead-in are its items: all of them, or all but the last when that one reads as a closing sentence (see the module doc: three or more lines, it starts with a capital letter,
    none before it does)."""
    bodies = [_body(e) for e in after]
    if len(after) >= 3 and bodies[-1][:1].isupper() and not any(b[:1].isupper() for b in bodies[:-1]):
        return len(after) - 1
    return len(after)


def _runs(meta: dict[str, Any], keeper: str) -> list[tuple[int, list[tuple[str, str]]]]:
    """[(position of the run's first line among the lines of next, the run)]: the runs of open lines of next that a split made and that are fit to read as a list: consecutive, single-line, his, one writer, in the
    record of the split, none of them the server's own line for the step and none waiting on a proof."""
    group = {k for k in meta.get("step_lines") or [] if isinstance(k, str)} if str(meta.get("step") or "").strip() else set()
    if not group:
        return []
    proofs = meta.get("step_proof") if isinstance(meta.get("step_proof"), dict) else {}
    rec = _steps.key(meta.get(_os.KEY)) if _steps.clean(meta.get(_os.KEY)) else ""

    def fit(e: str) -> bool:
        k = _steps.key(e)
        return "\n" not in e.strip() and k in group and k != rec and k not in proofs and _os.is_named(e)

    rows = _nl.resolve(meta, keeper)
    out: list[tuple[int, list[tuple[str, str]]]] = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and fit(rows[j][0]) and rows[j][1] == rows[i][1]:
            j += 1
        if j - i >= RUN_MIN:
            out.append((i, rows[i:j]))
        i = max(j, i + 1)
    return out


def _plans(meta: dict[str, Any], keeper: str) -> list[Plan]:
    out: list[Plan] = []
    for start, run in _runs(meta, keeper):
        entries = [e for e, _ in run]
        at = next((i for i, e in enumerate(entries) if _body(e).endswith(":") and len(entries) - i - 1 >= 2), None)
        if at is None:
            continue
        n = _closing_split(entries[at + 1:])
        if n >= 2:
            out.append(Plan(start + at, n, entries[at], entries[at + 1:at + 1 + n], entries[:at] + entries[at + 1 + n:]))
    return out


def plan(meta: dict[str, Any] | None, keeper: str = "") -> list[tuple[str, list[str], list[str]]]:
    """[(the lead-in line, the lines that become its items, the other lines of its run, which stay as they are)] for an item as it stands: what `nest` would do, nothing changed. [] when it has none."""
    return [(p.lead, p.items, p.left) for p in _plans(meta or {}, keeper)]


def merged(lead: str, items: list[str]) -> str:
    """The line the lead-in becomes: its words, then each item as a `- ` line indented under it."""
    return lead.strip() + "".join("\n" + _ss.SUB + _body(x) for x in items)


def _summary(meta: dict[str, Any], rows: list[tuple[str, str]], removed: int, edits: dict[int, str]) -> int | None:
    """Reword the summary and the server's line for it (see the module doc): `edits` gets the line's new text by its position, `meta` the step and owner_step. → the position of the server's line when it was reworded;
    nothing is changed when the summary is left as it was."""
    step = str(meta.get("step") or "").strip()
    m = _TAIL.match(step)
    if not m or not removed:
        return None
    new = m["head"] + (_ss.MORE_FORM.format(n=int(m["n"]) - removed) if int(m["n"]) > removed else "")
    rec = _steps.clean(meta.get(_os.KEY))
    if rec:
        proofs = meta.get("step_proof") if isinstance(meta.get("step_proof"), dict) else {}
        at = next((i for i, (e, _) in enumerate(rows) if _steps.key(e) == _steps.key(rec)), None)
        if at is None or not _os.same_line(rec, _os.line_of(step)) or _steps.key(rec) in proofs or "\n" in rows[at][0].strip():
            return None
        edits[at] = _os.line_of(new)
        meta[_os.KEY] = edits[at]
        meta["step"] = new
        return at
    meta["step"] = new
    return None


def nest(meta: dict[str, Any], keeper: str = "") -> list[dict[str, Any]]:
    """Put the item's flat lists into the new shape, in place (metadata.next and next_by, metadata.steps, metadata.step_lines, and the summary with the server's line for it). → [{lead, items, left}] for each list
    nested: the lead-in's first line, the items' words, and the lines of the run that stay lines of their own. [] (and nothing changed) when there is none."""
    plans = _plans(meta, keeper)
    if not plans:
        return []
    rows = _nl.resolve(meta, keeper)
    cl, where = _steps.view_rows(meta, keeper=keeper)
    edits = {p.at: merged(p.lead, p.items) for p in plans}
    gone = {i for p in plans for i in range(p.at + 1, p.at + 1 + p.n)}
    renamed = {_steps.key(rows[i][0]): _steps.key(t) for i, t in edits.items()}
    mirror = _summary(meta, rows, len(gone), edits)
    cl = [({**s, "text": edits[j]} if j in edits else s) for s, j in zip(cl, where) if j not in gone]
    new_rows_all = [(edits.get(i, e), w) for i, (e, w) in enumerate(rows)]
    new_rows = [r for i, r in enumerate(new_rows_all) if i not in gone]
    _nl.set_rows(meta, new_rows)
    if "steps" in meta:
        meta["steps"] = _steps.stored(cl)
    have = {_steps.key(e) for i, (e, _) in enumerate(new_rows_all) if i not in gone and i != mirror}      # the server's line for the summary is no line of the split, whatever its words
    lines: list[str] = []
    for k in [k for k in meta.get("step_lines") or [] if isinstance(k, str)]:
        for x in (renamed.get(k), k):
            if x and x in have and x not in lines:
                lines.append(x)
    meta["step_lines"] = lines
    return [{"lead": _steps.first_line(p.lead), "items": [_body(x) for x in p.items], "left": [_steps.first_line(e) for e in p.left]} for p in plans]
